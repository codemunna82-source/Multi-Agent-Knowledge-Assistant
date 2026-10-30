"""Document summaries in several styles: short, detailed, executive, chapter-by-chapter and a single named section.
Whole documents are covered (map-reduce over every unit); with an LLM the text is abstractive, without one it is extractive."""
from __future__ import annotations

import re

from ..core import ProviderError, format_loc
from ..tools.summarise import SYSTEM, extractive, summarise_chunks
from .entities import extract_source

STYLES = ("short", "detailed", "executive", "chapter", "section")
PAGES_PER_BLOCK = 10
UNITS_PER_BLOCK = 40
MAX_SECTION_CHARS = 120_000


def _group(units) -> list[dict]:
    """Units -> ordered sections [{"title","units","pages":(a,b)|None,"loc"}]: by heading when the document has them, else fixed page/unit blocks."""
    groups: list[dict] = []
    if any(u.loc.get("section") for u in units):
        for u in units:
            title = u.loc.get("section") or "(before the first heading)"
            if not groups or groups[-1]["title"] != title:
                groups.append({"title": title, "units": []})
            groups[-1]["units"].append(u)
    else:
        step_by_page = any("page" in u.loc for u in units)
        for u in units:
            if step_by_page:
                n = (u.loc.get("page", 1) - 1) // PAGES_PER_BLOCK
                title = f"pages {n * PAGES_PER_BLOCK + 1}-{(n + 1) * PAGES_PER_BLOCK}"
            else:
                n = len(sum((g["units"] for g in groups), [])) // UNITS_PER_BLOCK
                title = f"part {n + 1}"
            if not groups or groups[-1]["title"] != title:
                groups.append({"title": title, "units": []})
            groups[-1]["units"].append(u)
    for g in groups:
        pages = [u.loc["page"] for u in g["units"] if "page" in u.loc]
        g["pages"] = (min(pages), max(pages)) if pages else None
        g["loc"] = g["units"][0].loc
    return groups


def _summ(texts: list[str], llm, n_sentences: int | None = None) -> tuple[str, bool]:
    text = "\n".join(texts)[:MAX_SECTION_CHARS]
    s, calls = summarise_chunks([{"text": text}], llm)
    used_llm = bool(llm is not None and getattr(llm, "available", False))
    if n_sentences:
        s = _shorten(s, n_sentences, llm if used_llm else None)
    return s, used_llm


def _shorten(text: str, n: int, llm=None) -> str:
    if llm is not None:
        try:
            return llm.complete(SYSTEM, f"Rewrite as at most {n} sentences, keeping only the most important facts:\n<text>\n{text[:6000]}\n</text>")
        except ProviderError:
            pass
    return extractive(text, n) or text[:400]


def summarize_source(k, st, meta: dict, style: str = "detailed", section: str | None = None, max_sections: int = 60) -> dict:
    if style not in STYLES:
        raise ValueError(f"style must be one of {', '.join(STYLES)}")
    llm = k.llm if k.llm.available else None
    if meta.get("tabular"):
        cols = "; ".join(f"{(t['sheet'] + ': ') if t['sheet'] else ''}{t['rows']} rows, columns {', '.join(t['columns'])}" for t in meta.get("tables", []))
        text = f"Spreadsheet with {cols}. Use the analytics endpoints for figures."
        return {"source_id": meta["id"], "source": meta["name"], "style": style, "summary": text, "sections": [], "method": "structure", "units": meta.get("units")}
    units = [u for _, u in st.iter_units([meta["id"]])]
    if not units:
        return {"source_id": meta["id"], "source": meta["name"], "style": style, "summary": "", "sections": [], "method": "none", "units": 0}
    method = "llm" if llm else "extractive"
    out: dict = {"source_id": meta["id"], "source": meta["name"], "style": style, "units": len(units), "sections": [], "method": method}
    if style in ("chapter", "section"):
        groups = _group(units)
        if style == "section":
            if not section:
                raise ValueError("style 'section' needs a section title")
            want = re.sub(r"\s+", " ", section).strip().lower()
            groups = [g for g in groups if want in g["title"].lower()]
            if not groups:
                raise LookupError(f"No section matching '{section}'")
        truncated = len(groups) > max_sections
        for g in groups[:max_sections]:
            text, used = _summ([u.text for u in g["units"]], llm)
            out["sections"].append({"title": g["title"], "pages": list(g["pages"]) if g["pages"] else None, "location": format_loc(g["loc"]), "loc": g["loc"], "summary": text, "units": len(g["units"])})
        out["truncated"] = truncated
        out["summary"] = "\n\n".join(f"{s['title']}: {s['summary']}" for s in out["sections"])
        return out
    full, _ = _summ([u.text for u in units], llm)
    if style == "short":
        out["summary"] = _shorten(full, 3, llm)
    elif style == "detailed":
        out["summary"] = full
    else:  # executive
        ents = extract_source(units, llm)["entities"]
        figures = []
        for typ in ("MONEY", "PERCENT", "DATE"):
            figures += [f"{e['value']} ({typ.lower()}, {e['locations'][0] if e['locations'] else 'document'})" for e in ents.get(typ, [])[:3]]
        if llm is not None:
            try:
                out["summary"] = llm.complete(SYSTEM, "Write an executive summary with: Purpose, Key points (max 5 bullets), Figures and dates, Risks or open questions, Recommended next steps. "
                                                      f"Use only the text.\n<text>\n{full[:8000]}\n</text>")
            except ProviderError:
                llm = None
        if llm is None:
            out["summary"] = "Overview: " + _shorten(full, 3) + ("\nKey figures: " + "; ".join(figures[:8]) if figures else "") + "\nKey points:\n" + "\n".join(f"- {s}" for s in extractive(full, 5).split(". ")[:5] if s.strip())
            out["method"] = "extractive"
        out["figures"] = figures[:8]
    return out
