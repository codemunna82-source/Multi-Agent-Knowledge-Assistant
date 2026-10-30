"""Question generation for a source: LLM-written from a spread of chunks (validated), or templated from facts we actually observed
(sections, entities, table columns). Spreadsheet questions are phrased so the Pandas agent can answer them."""
from __future__ import annotations

import re

from ..core import ProviderError
from ..rag.steps import parse_json
from ..security.injection import SYSTEM_GUARD, wrap_untrusted
from .entities import extract_source


def _valid(qs, n) -> list[str]:
    out = []
    for q in qs if isinstance(qs, list) else []:
        if isinstance(q, str):
            q = " ".join(q.split())
            if 10 <= len(q) <= 180 and q.endswith("?") and q.lower() not in {x.lower() for x in out}:
                out.append(q)
    return out[:n]


def generate_questions(k, st, meta: dict, n: int = 8) -> dict:
    units = [u for _, u in st.iter_units([meta["id"]])]
    if meta.get("tabular"):
        qs = []
        for t in meta.get("tables", []):
            sheet = f" in sheet {t['sheet']}" if t["sheet"] else ""
            qs += [f"How many rows are there{sheet}?", "Are there any duplicate rows?"]
        cols = [c for t in meta.get("tables", []) for c in t["columns"]]
        qs += [f"What are the distinct values of {c}?" for c in cols[:2]]
        return {"method": "template", "questions": qs[:n]}
    if k.llm.available and units:
        step = max(1, len(units) // 10)
        text = "\n".join(u.text[:600] for u in units[::step][:10])
        sys = f'Write {n} diverse questions a reader could ask that are answerable from this text. JSON only: {{"questions": ["...?"]}}. {SYSTEM_GUARD}'
        try:
            j = parse_json(k.llm.complete(sys, wrap_untrusted(text, meta["name"])))
            good = _valid((j or {}).get("questions") if isinstance(j, dict) else None, n)
            if good:
                return {"method": "llm", "questions": good}
        except ProviderError:
            pass
    qs: list[str] = []
    sections = list(dict.fromkeys(u.loc["section"] for u in units if u.loc.get("section")))
    qs += [f"What does the document say about {s}?" for s in sections[:4]]
    ents = extract_source(units)["entities"]
    qs += [f'Where is "{e["value"]}" mentioned?' for e in ents.get("NAME", [])[:2] + ents.get("ORG", [])[:1]]
    if ents.get("MONEY"):
        qs.append(f'What is the {ents["MONEY"][0]["value"]} amount related to?')
    if ents.get("DATE"):
        qs.append(f'What happens on {ents["DATE"][0]["value"]}?')
    qs.append(f"Summarize {meta['name']}")
    return {"method": "template", "questions": _valid(qs, n)}
