"""Document classification into a closed taxonomy. Default: transparent keyword/structure scorer (works offline, no model).
With an LLM: the model must answer with a label from the taxonomy (anything else is rejected) and the heuristic result is the fallback."""
from __future__ import annotations

import math
import re

from ..core import ProviderError, Unit
from ..rag.steps import parse_json
from ..security.injection import SYSTEM_GUARD, wrap_untrusted

TAXONOMY: dict[str, list[str]] = {
    "contract": ["agreement", "parties", "party", "hereby", "clause", "termination", "indemnif", "governing law", "whereas", "confidentiality", "witness", "obligations", "warranty", "liability", "अनुबंध", "समझौता"],
    "invoice": ["invoice", "amount due", "bill to", "subtotal", "total due", "payment terms", "unit price", "qty", "tax invoice", "due date", "चालान"],
    "resume": ["curriculum vitae", "resume", "work experience", "education", "skills", "objective", "references", "employment history", "certifications", "बायोडाटा"],
    "policy": ["policy", "procedure", "employees must", "compliance", "effective date", "scope", "purpose", "responsibilities", "prohibited", "approval", "नीति"],
    "report": ["executive summary", "findings", "conclusion", "recommendations", "methodology", "introduction", "analysis", "quarterly", "annual report", "overview", "रिपोर्ट"],
    "research_paper": ["abstract", "keywords", "references", "doi", "et al", "methodology", "results", "discussion", "figure", "hypothesis", "dataset"],
    "meeting_notes": ["attendees", "agenda", "action items", "minutes", "decisions", "next meeting", "present:", "apologies"],
    "financial_statement": ["balance sheet", "income statement", "revenue", "ebitda", "assets", "liabilities", "cash flow", "net profit", "equity", "depreciation"],
    "technical_documentation": ["api", "installation", "configuration", "usage", "endpoint", "parameters", "error code", "version", "deploy", "prerequisites", "command"],
    "email": ["from:", "to:", "subject:", "regards", "sincerely", "dear", "cc:", "sent:"],
    "legal_notice": ["notice", "hereby notified", "pursuant to", "court", "plaintiff", "defendant", "hereinafter", "jurisdiction", "counsel"],
}
NAME_HINTS = {"invoice": "invoice", "contract": "contract", "agreement": "contract", "resume": "resume", "cv": "resume", "policy": "policy", "minutes": "meeting_notes",
              "notes": "meeting_notes", "report": "report", "statement": "financial_statement", "manual": "technical_documentation", "readme": "technical_documentation"}
LABELS = tuple(TAXONOMY) + ("dataset", "other")


def _score(text: str) -> dict[str, float]:
    low = text.lower()
    out = {}
    for label, kws in TAXONOMY.items():
        s = sum(min(low.count(k), 3) for k in kws if k in low)
        out[label] = s / math.sqrt(len(kws))
    return out


def classify(kind: str, name: str, units: list[Unit], llm=None, sample_chars: int = 8000) -> dict:
    """-> {"label", "confidence" (0-1), "method", "runner_up", "scores"}"""
    if kind in ("csv", "xlsx", "xls"):
        return {"label": "dataset", "confidence": 0.95, "method": "structure", "runner_up": None, "scores": {}}
    head, total = [], 0
    for u in units:
        head.append(u.text)
        total += len(u.text)
        if total >= sample_chars:
            break
    text = "\n".join(head)[:sample_chars + 2000]
    scores = _score(text)
    stem = re.sub(r"[^a-z]+", " ", name.lower()).split()
    for w in stem:  # a file called invoice_2024.pdf is a strong hint, never the only evidence
        if w in NAME_HINTS:
            scores[NAME_HINTS[w]] = scores.get(NAME_HINTS[w], 0) + 1.0
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    (top, ts), (second, ss) = ranked[0], ranked[1]
    if ts < 1.2:
        label, conf, method = "other", round(max(0.2, 0.6 - ts / 4), 2), "keywords"
    else:
        margin = (ts - ss) / (ts + 1e-9)
        label, conf, method = top, round(min(1.0, ts / 4) * (0.5 + 0.5 * margin), 2), "keywords"
    res = {"label": label, "confidence": conf, "method": method, "runner_up": second if ss > 0 else None, "scores": {k: round(v, 2) for k, v in ranked[:4]}}
    if llm is not None and getattr(llm, "available", False) and text.strip():
        sys = f'Classify the document into exactly one of: {", ".join(LABELS)}. JSON only: {{"label": "...", "confidence": 0-1}}. {SYSTEM_GUARD}'
        try:
            j = parse_json(llm.complete(sys, wrap_untrusted(text[:3500], name)))
        except ProviderError:
            j = None
        if isinstance(j, dict) and j.get("label") in LABELS and isinstance(j.get("confidence"), (int, float)):
            res.update(label=j["label"], confidence=round(max(0.0, min(1.0, float(j["confidence"]))), 2), method="llm", heuristic=label)
    return res
