from __future__ import annotations

import re

from ..core import stem, tokenize
from ..schemas import Citation

NOT_VERIFIED = "I could not verify an answer from the indexed sources."


def fmt(v) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) and not float(v).is_integer() else f"{int(v):,}"


def excerpt(text: str, n: int = 300) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def result(route: str, answer: str, **kw) -> dict:
    kw.setdefault("confidence", "none")
    kw.setdefault("verified", kw["confidence"] != "none")
    kw.setdefault("citations", [])
    kw.setdefault("limitations", [])
    kw.setdefault("details", {})
    kw.setdefault("needs_input", False)
    kw["citations"] = [c.model_dump() if isinstance(c, Citation) else c for c in kw["citations"]]
    return {"route": route, "answer": answer, **kw}


def split_sentences(text: str, keep_lines: bool = False) -> list[str]:
    """Sentence split. Single newlines are layout (hard-wrapped PDF lines) unless the text is row/line structured (`keep_lines`)."""
    if not keep_lines:
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    return [p.strip() for p in re.split(r"(?<=[.!?।。])\s+|\n+", text) if p.strip()]


def _structured(location: str) -> bool:
    return bool(re.search(r"\b(row|rows|path|table)\b", location))


def best_sentences(evidence: list[dict], query: str, n: int = 3) -> list[tuple[dict, str]]:
    """Verbatim sentences from the evidence that overlap most with the query (the extractive, no-LLM answer)."""
    qs = {stem(t) for t in tokenize(query)}
    scored = []
    for e in evidence:
        for s in split_sentences(e.get("context") or e["text"], _structured(e.get("location", ""))):
            s = s.strip()
            if len(s) < 15:
                continue
            ov = len(qs & {stem(t) for t in tokenize(s)})
            scored.append((ov, e.get("score", 0.0), e, s))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    seen, out = set(), []
    for ov, _, e, s in scored:
        if ov == 0 and out:
            break
        if s in seen:
            continue
        seen.add(s)
        out.append((e, s))
        if len(out) >= n:
            break
    return out or [(e, excerpt(e.get("context") or e["text"], 250)) for e in evidence[:1]]


def hit_to_evidence(i: int, h) -> dict:
    return {"i": i, "chunk_id": h.chunk_id, "source_id": h.source_id, "source": h.source, "location": h.location, "text": h.text, "context": h.llm_text,
            "score": round(h.score, 4), "lexical": round(h.lexical, 3), "suspicious": h.suspicious, "rerank": h.rerank}


def evidence_citations(evidence: list[dict]) -> list[dict]:
    return [Citation(source_id=e["source_id"], source=e["source"], location=e["location"], excerpt=excerpt(e["text"]), score=e.get("score") or None).model_dump()
            for e in evidence]


def confidence_from(evidence: list[dict], grade: str) -> str:
    if not evidence:
        return "none"
    top = evidence[0]
    if grade == "correct" and (top.get("lexical", 0) >= 0.8 or top.get("score", 0) >= 0.5):
        return "high"
    return "medium" if grade == "correct" or top.get("lexical", 0) >= 0.5 else "low"
