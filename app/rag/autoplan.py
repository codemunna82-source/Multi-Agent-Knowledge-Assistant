"""Automatic retrieval-strategy selection (the `strategy` node of the agent graph).

1. Look at the question (quoted text, IDs and numbers, relational wording, script, length) and propose up to three candidate configurations,
   each with the reason it was proposed.
2. Run every candidate through the real retrieval pipeline and score it: grade (correct > ambiguous > incorrect), how many passages survived the
   relevance gate, lexical coverage and similarity of the top hit. Latency is shown but does not decide.
3. Keep the best. The full table (candidates, scores, reasons) is returned so the UI can show *why* - nothing here is hidden.

No model is required; the choice is empirical rather than guessed. Ties go to the earlier (simpler) candidate."""
from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Optional

from ..core import NOSPACE

CANDIDATES: dict[str, dict] = {
    "keyword-first": {"mode": "keyword", "reranker": "lexical", "compression": True, "parent_child": True, "rewrite": False},
    "hybrid": {"mode": "hybrid", "reranker": "lexical", "compression": True, "parent_child": True},
    "hybrid + multi-query": {"mode": "hybrid", "multi_query": True, "reranker": "lexical", "compression": True, "parent_child": True},
    "semantic": {"mode": "semantic", "reranker": "lexical", "compression": True, "parent_child": True},
    "hybrid + graph": {"mode": "hybrid", "graph": True, "reranker": "lexical", "compression": True, "parent_child": True},
    "hybrid + cross-lingual": {"mode": "hybrid", "cross_lingual": True, "reranker": "lexical", "compression": True, "parent_child": True},
}
QUOTED = re.compile(r"[\"“'‘][^\"”'’]{2,}[\"”'’]")
IDLIKE = re.compile(r"(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{4,}")
RELATIONAL = re.compile(r"\b(related|relationship|connected|linked|between|works? with|reports? to|who .* and)\b", re.I)
CONCEPTUAL = re.compile(r"\b(why|how|explain|describe|summar\w+|difference|policy|process|reason|benefit|impact|meaning|about)\b", re.I)


def features(question: str) -> dict:
    words = question.split()
    caps = re.findall(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", question)
    return {"words": len(words), "quoted": bool(QUOTED.search(question)), "id_like": bool(IDLIKE.search(question)), "has_number": bool(re.search(r"\d", question)),
            "relational": bool(RELATIONAL.search(question)) or len(caps) >= 2, "conceptual": bool(CONCEPTUAL.search(question)),
            "non_latin": bool(NOSPACE.search(question)) or sum(1 for ch in question if ord(ch) > 0x2FF and ch.isalpha()) > 0.3 * max(1, len(question)), "entities": caps[:4]}


def propose(f: dict, doc_languages: set[str]) -> list[tuple[str, str]]:
    """-> [(candidate name, why)], most plausible first, at most three."""
    out: list[tuple[str, str]] = []
    if f["quoted"] or f["id_like"]:
        out.append(("keyword-first", "the question contains a quoted phrase or an ID-like token: exact words matter more than meaning"))
    if f["non_latin"] or (doc_languages - {"en"}):
        out.append(("hybrid + cross-lingual", "the question or the documents are not English: translated query variants (needs a model) help"))
    if f["relational"]:
        out.append(("hybrid + graph", "the question asks how entities relate: the knowledge graph links passages that mention them together"))
    out.append(("hybrid", "balanced default: BM25 and vectors fused with RRF"))
    if f["conceptual"] or f["words"] >= 9:
        out.append(("hybrid + multi-query", "a long or conceptual question: several phrasings widen the candidate pool"))
        out.append(("semantic", "conceptual wording: meaning-based search alone can beat keyword noise"))
    elif not f["quoted"]:
        out.append(("keyword-first", "short factual question: keyword search is fast and precise"))
    seen, uniq = set(), []
    for n, w in out:
        if n not in seen:
            seen.add(n)
            uniq.append((n, w))
    return uniq[:3]


def score(res, top_k: int, ms: float = 0.0) -> float:
    """Quality only (latency is reported but does not decide): equal-quality candidates keep the order of `propose`, so the simpler one wins ties."""
    if res.abstain or not res.hits:
        return -1.0
    rank = {"correct": 2, "ambiguous": 1, "incorrect": 0}[res.grade]
    top = res.hits[0]
    return round(rank * 10 + 2 * min(len(res.hits), top_k) / top_k + 2 * top.lexical + 2 * min(max(top.score, 0.0), 1.0), 3)


def choose(pipeline, st, question: str, base, source_ids: Optional[list[str]], doc_languages: set[str], llm_available: bool) -> dict:
    f = features(question)
    rows, best = [], None
    for name, why in propose(f, doc_languages):
        ov = CANDIDATES[name]
        if not llm_available and name == "hybrid + cross-lingual":
            why += " [no model configured: the translation step will be skipped]"
        opts = replace(base, **ov, auto=False, corrective=False, max_retries=0)
        t0 = time.perf_counter()
        res = pipeline.retrieve(st, question, opts, source_ids, None, None)
        ms = (time.perf_counter() - t0) * 1000
        sc = score(res, base.top_k, ms)
        row = {"name": name, "why": why, "grade": res.grade, "hits": len(res.hits), "top_source": res.hits[0].source if res.hits else None, "top_location": res.hits[0].location if res.hits else None,
               "top_lexical": round(res.hits[0].lexical, 3) if res.hits else None, "ms": round(ms, 1), "score": sc, "overrides": ov}
        rows.append(row)
        if best is None or sc > best["score"] + 0.01:  # a candidate must beat the current best by a margin, otherwise the earlier one stays
            best = row
    best["chosen"] = True
    return {"chosen": best["name"], "why": best["why"], "overrides": best["overrides"], "features": f, "candidates": rows}
