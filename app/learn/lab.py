"""Retrieval lab: run the same question through different retrieval configurations and report what each one retrieved, so the effect of every technique is visible."""
from __future__ import annotations

import time
from dataclasses import replace

BARE = {"mode": "semantic", "rewrite": False, "multi_query": False, "hyde": False, "parent_child": False, "compression": False, "reranker": "none", "corrective": False, "graph": False, "cross_lingual": False}
PRESETS: dict[str, dict] = {
    "semantic only": {}, "keyword only (BM25)": {"mode": "keyword"}, "hybrid (RRF)": {"mode": "hybrid"}, "hybrid + rewrite": {"mode": "hybrid", "rewrite": True},
    "hybrid + multi-query": {"mode": "hybrid", "multi_query": True}, "hybrid + HyDE": {"mode": "hybrid", "hyde": True}, "hybrid + graph": {"mode": "hybrid", "graph": True},
    "hybrid + rerank": {"mode": "hybrid", "reranker": "lexical"}, "hybrid + parent-child": {"mode": "hybrid", "parent_child": True}, "hybrid + compression": {"mode": "hybrid", "compression": True},
    "hybrid + corrective": {"mode": "hybrid", "corrective": True, "max_retries": 2},
    "everything on": {"mode": "hybrid", "rewrite": True, "multi_query": True, "graph": True, "reranker": "lexical", "parent_child": True, "compression": True, "corrective": True, "max_retries": 2},
}
ABLATION: list[tuple[str, dict]] = [("1. semantic only (bare)", {}), ("2. + BM25 → hybrid", {"mode": "hybrid"}), ("3. + query rewrite", {"rewrite": True}), ("4. + multi-query", {"multi_query": True}),
                                    ("5. + graph expansion", {"graph": True}), ("6. + lexical rerank", {"reranker": "lexical"}), ("7. + parent-child context", {"parent_child": True}),
                                    ("8. + contextual compression", {"compression": True}), ("9. + corrective loop", {"corrective": True, "max_retries": 2})]
NEEDS_MODEL = {"multi_query": "multi-query needs a model to write other phrasings (without one it falls back to a deterministic variant)", "hyde": "HyDE needs a model to write the hypothetical answer (without one this step is skipped)",
               "cross_lingual": "translation needs a model"}


def _trace(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        item = {"step": e.get("step"), **{k: v for k, v in e.items() if k not in ("step",) and isinstance(v, (str, int, float, bool, list)) and k != "attempt"}}
        if "attempt" in e and e["attempt"]:
            item["attempt"] = e["attempt"]
        out.append(item)
    return out


def run_one(pipeline, k, st, question: str, name: str, base, overrides: dict, source_ids: list[str] | None, top: int = 5) -> dict:
    opts = replace(base, **{**BARE, **overrides}, auto=False)
    t0 = time.perf_counter()
    res = pipeline.retrieve(st, question, opts, source_ids, None, None)
    ms = (time.perf_counter() - t0) * 1000
    hits = [{"rank": i, "chunk_id": h.chunk_id, "source": h.source, "location": h.location, "score": round(h.score, 3), "lexical": round(h.lexical, 2), "fused": round(h.fused, 4),
             "rerank": None if h.rerank is None else round(h.rerank, 3), "chars_matched": len(h.text), "chars_to_model": len(h.llm_text), "compressed": h.compressed, "excerpt": " ".join(h.llm_text.split())[:260]}
            for i, h in enumerate(res.hits[:top], 1)]
    notes = [msg for key, msg in NEEDS_MODEL.items() if overrides.get(key) and not k.llm.available]
    return {"name": name, "overrides": overrides, "grade": res.grade, "abstained": res.abstain, "query_used": res.query, "attempts": res.attempts, "ms": round(ms, 1), "hits": hits, "trace": _trace(res.trace), "notes": notes}


def with_deltas(rows: list[dict], reference: int | None = None) -> list[dict]:
    """Annotate each row with how its top results differ from the previous row (ablation) or from a reference row (compare)."""
    for i, r in enumerate(rows):
        ref = rows[i - 1] if reference is None and i else (rows[reference] if reference is not None and i != reference else None)
        mine = [h["chunk_id"] for h in r["hits"]]
        if ref is None:
            r["delta"] = None
            continue
        theirs = [h["chunk_id"] for h in ref["hits"]]
        union = set(mine) | set(theirs)
        r["delta"] = {"vs": ref["name"], "overlap": round(len(set(mine) & set(theirs)) / len(union), 2) if union else 1.0, "new": [h["location"] + " · " + h["source"] for h in r["hits"] if h["chunk_id"] not in theirs],
                      "dropped": [h["location"] + " · " + h["source"] for h in ref["hits"] if h["chunk_id"] not in mine], "same_top1": bool(mine and theirs and mine[0] == theirs[0]),
                      "grade_changed": None if ref["grade"] == r["grade"] else f"{ref['grade']} → {r['grade']}", "ms_change": round(r["ms"] - ref["ms"], 1),
                      "chars_to_model_change": sum(h["chars_to_model"] for h in r["hits"]) - sum(h["chars_to_model"] for h in ref["hits"])}
    return rows
