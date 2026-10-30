"""Configurable advanced-RAG pipeline.

 query -> [rewrite] -> [multi-query / HyDE] -> semantic + keyword retrieval (metadata-filtered) -> RRF fusion -> relevance gate
       -> parent expansion + de-duplication -> rerank -> top-k -> [contextual compression] -> grade -> [corrective retry loop]

Every step is optional/configurable (see rag.options) and recorded in `trace` for debugging and evaluation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..core import format_loc
from ..storage import SessionStore
from . import steps
from .index import IndexCache, ScopeIndex, terms
from .options import Resolved
from .types import Hit

log = logging.getLogger("mka.rag")


@dataclass
class RetrievalResult:
    hits: list[Hit] = field(default_factory=list)
    grade: str = "incorrect"  # correct | ambiguous | incorrect
    abstain: bool = False  # corrective loop exhausted without relevant evidence
    query: str = ""  # the (possibly rewritten) query that produced the hits
    trace: list[dict] = field(default_factory=list)
    attempts: int = 0
    excluded_suspicious: int = 0


class RAGPipeline:
    def __init__(self, knowledge):
        self.k = knowledge
        self.cache = IndexCache()
        self.graphs = None  # set by the Assistant (GraphCache)

    # ------------------------------------------------------------------ public
    def retrieve(self, st: SessionStore, query: str, opts: Resolved, source_ids: Optional[list[str]] = None,
                 last_question: Optional[str] = None, summary: Optional[str] = None) -> RetrievalResult:
        llm = self.k.llm if self.k.llm.available else None
        idx = self.cache.index(st)
        res = RetrievalResult(query=query)
        allowed = [sid for sid in idx.metas if source_ids is None or sid in source_ids]
        if not idx.chunks or not allowed:
            res.trace.append({"step": "empty-index"})
            res.abstain = True
            return res

        q = query
        if opts.rewrite:
            q, how = steps.rewrite_query(llm, query, last_question, summary)
            res.trace.append({"step": "rewrite", "method": how, "query": q})

        extra: list[str] = []
        if opts.cross_lingual and llm is not None:
            from ..intel.language import detect_language

            doc_langs = {idx.metas[sid].get("language", "en") for sid in allowed}
            targets = sorted(doc_langs - {detect_language(q)})
            if targets:
                extra = steps.translate_query(llm, q, targets)
                res.trace.append({"step": "cross-lingual", "targets": targets, "translations": extra})

        best: Optional[RetrievalResult] = None
        mode_opts = opts
        for attempt in range(opts.max_retries + 1 if opts.corrective else 1):
            res_try = self._once(st, idx, q, mode_opts, allowed, llm, attempt, extra)
            res_try.query = q
            res.trace.extend({**t, "attempt": attempt} for t in res_try.trace)
            rank = {"correct": 2, "ambiguous": 1, "incorrect": 0}
            if best is None or rank[res_try.grade] > rank[best.grade] or (rank[res_try.grade] == rank[best.grade] and len(res_try.hits) > len(best.hits)):
                best = res_try
            res.attempts = attempt + 1
            if res_try.grade == "correct" or not opts.corrective:
                break
            if attempt >= opts.max_retries:
                break
            # --- corrective action (bounded by max_retries)
            rare = sorted(set(terms(q)), key=lambda t: -idx.bm25.idf.get(t, 0.0))
            if res_try.grade == "incorrect":
                q, how = steps.reformulate(llm, q, attempt + 1, rare)
                res.trace.append({"step": "corrective-reformulate", "method": how, "query": q, "attempt": attempt})
            else:
                res.trace.append({"step": "corrective-broaden", "attempt": attempt})
            mode_opts = _broaden(mode_opts)

        res.hits, res.grade = best.hits, best.grade
        res.query = best.query
        res.excluded_suspicious = best.excluded_suspicious
        if res.grade == "incorrect":
            res.hits, res.abstain = [], True
        return res

    # ------------------------------------------------------------------ one retrieval pass
    def _once(self, st: SessionStore, idx: ScopeIndex, q: str, o: Resolved, allowed: list[str], llm, attempt: int, extra: Optional[list[str]] = None) -> RetrievalResult:
        r = RetrievalResult()
        allowed_set = set(allowed)
        variants = [q] + [t for t in (extra or []) if t != q]
        if o.multi_query:
            extra, how = steps.multi_queries(llm, q, o.multi_query_n)
            variants += extra
            r.trace.append({"step": "multi-query", "method": how, "queries": variants})
        hyde_text = steps.hyde_passage(llm, q) if o.hyde else None
        if o.hyde:
            r.trace.append({"step": "hyde", "used": bool(hyde_text)})

        flt = o.filters
        keep = (lambda cid: idx.passes(flt, idx.by_id[cid])) if flt.active() else (lambda cid: True)  # noqa: E731
        pool = o.pool * (1 + attempt)  # corrective passes widen the candidate pool
        overfetch = pool * (3 if flt.active() else 1)
        rankings: list[list[str]] = []
        cos: dict[str, float] = {}
        q_terms = terms(q)

        for v in variants:
            if o.mode in ("semantic", "hybrid"):
                vec = self.k.backend.search(st, self.k.embedder.embed_query(v), overfetch, list(allowed_set), self.k.embedder.name)
                rankings.append([cid for cid, _ in vec if cid in idx.by_id and keep(cid)][:pool])
                for cid, sc in vec:
                    cos[cid] = max(cos.get(cid, -1.0), sc)
            if o.mode in ("keyword", "hybrid"):
                vt = terms(v)
                sc = idx.bm25.scores(vt if attempt == 0 else idx.bm25.expand(vt))
                ranked = sorted(sc, key=lambda i: -sc[i])
                rankings.append([idx.chunks[i]["id"] for i in ranked if idx.chunks[i]["id"].split(":", 1)[0] in allowed_set and keep(idx.chunks[i]["id"])][:pool])
        if hyde_text and o.mode in ("semantic", "hybrid"):
            vec = self.k.backend.search(st, self.k.embedder.embed_query(hyde_text), overfetch, list(allowed_set), self.k.embedder.name)
            rankings.append([cid for cid, _ in vec if cid in idx.by_id and keep(cid)][:pool])
            for cid, sc in vec:
                cos[cid] = max(cos.get(cid, -1.0), sc)

        if o.graph and getattr(self, "graphs", None) is not None:
            kg = self.graphs.get(st, allowed_set)
            keys = kg.find(q)
            if keys:
                gl = [cid for cid in kg.expand_chunks(keys, pool) if cid in idx.by_id and cid.split(":", 1)[0] in allowed_set and keep(cid)]
                rankings.append(gl)
                r.trace.append({"step": "graph-expand", "entities": [kg.nodes[k].name for k in keys], "chunks": len(gl)})

        fused: dict[str, float] = {}
        for rl in rankings:
            for rank, cid in enumerate(rl):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
        r.trace.append({"step": "retrieve", "mode": o.mode, "candidates": len(fused), "filters": flt.active()})

        # relevance gate + hit construction
        qsets = [set(terms(v)) for v in variants if terms(v)] or [set()]
        alts = {t: ({t} | set(idx.bm25.expand([t]))) if attempt > 0 else {t} for qs in qsets for t in qs}  # corrective passes tolerate inflections / typos
        hits: list[Hit] = []
        for cid, f in sorted(fused.items(), key=lambda kv: -kv[1]):
            c = idx.by_id[cid]
            ctoks = set(idx.ch_terms[idx.pos[cid]])
            # lexical coverage = best coverage over the original query and its variants
            overlap = max((sum(1 for t in qs if alts[t] & ctoks) / len(qs) if qs else 0.0) for qs in qsets)
            score = cos.get(cid, 0.0)
            if score < o.min_score and overlap < 0.5 and not (hyde_text and score >= o.min_score):
                continue
            sid = cid.split(":", 1)[0]
            hits.append(Hit(cid, sid, idx.metas[sid]["name"], format_loc(c["loc"], c.get("loc_end")), c["loc"], c["text"], score, overlap, f,
                            suspicious=idx.suspicious(c)))
        r.trace.append({"step": "gate", "kept": len(hits)})

        if o.injection_policy == "exclude":
            before = len(hits)
            hits = [h for h in hits if not h.suspicious]
            r.excluded_suspicious = before - len(hits)

        if o.parent_child:
            hits = self._expand_parents(st, idx, hits, o)
            r.trace.append({"step": "parent-expand", "parents": len(hits)})
        else:
            for h in hits:
                h.context = h.text

        # rerank
        hits = hits[: max(o.top_k * 3, o.top_k)]
        if hits and o.reranker != "none":
            bm = idx.bm25.scores(q_terms)
            mx = max(bm.values()) if bm else 1.0
            norm = {idx.chunks[i]["id"]: v / mx for i, v in bm.items() if mx} if bm else {}
            steps.lexical_rerank(hits, q_terms, norm)
            used = "lexical"
            if o.reranker == "llm" and llm is not None and steps.llm_rerank(llm, q, hits):
                used = "llm"
            elif o.reranker == "llm":
                used = "lexical (llm unavailable)"
            if o.reranker == "cross_encoder":
                ok = steps.cross_encoder_rerank(self.k.settings.cross_encoder_model, q, hits)
                used = "cross_encoder" if ok else "lexical (cross-encoder not installed)"
            hits.sort(key=lambda h: -(h.rerank or 0.0))
            r.trace.append({"step": "rerank", "method": used})
        hits = hits[: o.top_k]

        if o.compression:
            for h in hits:
                src = h.context or h.text
                out = steps.llm_compress(llm, src, q) if llm is not None else None
                comp = out or steps.extractive_compress(src, q)
                if comp != src:
                    h.context, h.compressed = comp, True
            r.trace.append({"step": "compress", "compressed": sum(h.compressed for h in hits)})

        grade = steps.grade_llm(llm, q, hits) if llm is not None else None
        r.grade = grade or steps.grade_heuristic(hits, o.min_score)
        r.hits = hits
        r.trace.append({"step": "grade", "grade": r.grade, "method": "llm" if grade else "heuristic"})
        return r

    # ------------------------------------------------------------------ parent-child
    def _expand_parents(self, st: SessionStore, idx: ScopeIndex, hits: list[Hit], o: Resolved) -> list[Hit]:
        seen: dict[tuple, Hit] = {}
        out: list[Hit] = []
        for h in hits:
            c = idx.by_id[h.chunk_id]
            key = (h.source_id, c.get("u0", 0), c.get("u1", 0))
            if key in seen:  # sibling child of an already-returned parent: keep only the best-ranked one
                continue
            units = self.cache.units(st, h.source_id)
            parent = "\n".join(u.text for u in units[c.get("u0", 0): c.get("u1", 0) + 1]) or h.text
            if len(parent) > o.parent_max_chars:  # center the window on the matched child
                pos = parent.find(h.text[:60])
                start = max(0, (pos if pos >= 0 else 0) - (o.parent_max_chars - len(h.text)) // 2)
                parent = parent[start: start + o.parent_max_chars]
            h.context, h.parent_key = parent, key
            seen[key] = h
            out.append(h)
        return out


def _broaden(o: Resolved) -> Resolved:
    from dataclasses import replace

    return replace(o, mode="hybrid", multi_query=True, reranker=o.reranker if o.reranker != "none" else "lexical")
