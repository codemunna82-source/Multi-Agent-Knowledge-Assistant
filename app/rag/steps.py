"""Individual RAG techniques. Each has an LLM implementation and, where meaningful, a deterministic fallback.
Every LLM output is validated; any failure degrades to the fallback instead of breaking the request."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..core import ProviderError, stem, tokenize
from ..security.injection import SYSTEM_GUARD, neutralize, wrap_untrusted
from .types import Hit

FOLLOWUP = re.compile(r"^(and|also|what about|how about|then|so|which|where|those|that|it|they|their|its)\b", re.I)


def parse_json(text: str):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।。])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


# ----------------------------------------------------------------------------- 1. query rewriting
def rewrite_query(llm, query: str, last_question: Optional[str], summary: Optional[str]) -> tuple[str, str]:
    """-> (standalone query, method). Resolves references to earlier turns so retrieval sees a self-contained question."""
    if llm is not None and llm.available and (last_question or summary):
        sys = "Rewrite the user's latest question as a standalone search query using the conversation context. Keep names, numbers and IDs exactly. " \
              'Reply with JSON only: {"query": "..."}'
        ctx = f"Conversation summary: {neutralize(summary or '')[:800]}\nPrevious question: {neutralize(last_question or '')[:300]}\nLatest question: {neutralize(query)[:500]}"
        try:
            j = parse_json(llm.complete(sys, ctx))
            q = (j or {}).get("query") if isinstance(j, dict) else None
            if isinstance(q, str) and 2 <= len(q) <= 400:
                return q.strip(), "llm"
        except ProviderError:
            pass
    if last_question and len(query.split()) <= 8 and FOLLOWUP.match(query.strip()):
        return f"{last_question} {query}", "context-merge"
    return query, "none"


# ----------------------------------------------------------------------------- 2. multi-query
def multi_queries(llm, query: str, n: int) -> tuple[list[str], str]:
    if llm is not None and llm.available:
        sys = f'Generate {n} alternative search queries (different wording, synonyms, possibly in other languages the documents may use) for the question. JSON only: {{"queries": ["..."]}}'
        try:
            j = parse_json(llm.complete(sys, neutralize(query)[:500]))
            qs = (j or {}).get("queries") if isinstance(j, dict) else None
            if isinstance(qs, list):
                out = [q.strip() for q in qs if isinstance(q, str) and 2 <= len(q.strip()) <= 300 and q.strip().lower() != query.lower()]
                if out:
                    return list(dict.fromkeys(out))[:n], "llm"
        except ProviderError:
            pass
    kw = " ".join(dict.fromkeys(tokenize(query)))
    return ([kw] if kw and kw != query.lower() else []), "keywords"


# ----------------------------------------------------------------------------- 3. HyDE
def hyde_passage(llm, query: str) -> Optional[str]:
    if llm is None or not llm.available:
        return None
    sys = "Write a short, factual-sounding passage (2-3 sentences) that would plausibly answer the question, as it might appear in a document. It will only be used for similarity search, never shown to the user."
    try:
        t = llm.complete(sys, neutralize(query)[:500]).strip()
        return t[:800] if t else None
    except ProviderError:
        return None


# ----------------------------------------------------------------------------- 4. reranking
def lexical_rerank(hits: list[Hit], q_terms: list[str], bm25_norm: dict[str, float]) -> None:
    qset = list(dict.fromkeys(q_terms))
    for h in hits:
        toks = [stem(t) for t in tokenize(h.text)]
        cov = len(set(qset) & set(toks)) / len(qset) if qset else 0.0
        phrase = 0.0
        for n in range(min(len(qset), 4), 1, -1):  # longest contiguous query n-gram found in the chunk
            grams = {tuple(qset[i:i + n]) for i in range(len(qset) - n + 1)}
            if any(tuple(toks[i:i + n]) in grams for i in range(len(toks) - n + 1)):
                phrase = n / max(len(qset), 1)
                break
        h.rerank = 0.45 * cov + 0.3 * bm25_norm.get(h.chunk_id, 0.0) + 0.15 * phrase + 0.1 * max(0.0, min(h.score, 1.0))


def llm_rerank(llm, query: str, hits: list[Hit]) -> bool:
    if not hits:
        return True
    sys = (f'Score each passage 0-10 for how well it helps answer the question. JSON only: {{"scores": [..one number per passage..]}}. {SYSTEM_GUARD}')
    body = "\n".join(f"[{i}] " + wrap_untrusted(h.text[:600], h.source) for i, h in enumerate(hits))
    try:
        j = parse_json(llm.complete(sys, f"Question: {neutralize(query)[:400]}\n{body}"))
    except ProviderError:
        return False
    sc = (j or {}).get("scores") if isinstance(j, dict) else None
    if not (isinstance(sc, list) and len(sc) == len(hits) and all(isinstance(x, (int, float)) for x in sc)):
        return False
    for h, x in zip(hits, sc):
        h.rerank = 0.7 * max(0.0, min(float(x), 10.0)) / 10 + 0.3 * (h.rerank or 0.0)
    return True


_ce = {}


def cross_encoder_rerank(model_name: str, query: str, hits: list[Hit]) -> bool:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        return False
    m = _ce.setdefault(model_name, CrossEncoder(model_name))
    for h, s in zip(hits, m.predict([(query, h.text) for h in hits])):
        h.rerank = float(s)
    return True


# ----------------------------------------------------------------------------- 5. contextual compression (verbatim only)
def extractive_compress(text: str, query: str, budget: int = 700) -> str:
    sents = _sentences(text)
    if sum(len(s) for s in sents) <= budget:
        return text
    qs = {stem(t) for t in tokenize(query)}
    scored = sorted(((len(qs & {stem(t) for t in tokenize(s)}), -i, i) for i, s in enumerate(sents)), reverse=True)
    keep, used = set(), 0
    for ov, _, i in scored:
        if ov == 0 and keep:
            break
        for j in (i,) + ((i + 1,) if i + 1 < len(sents) and ov else ()):  # the answer is often in the following sentence
            if j not in keep and used + len(sents[j]) <= budget:
                keep.add(j)
                used += len(sents[j])
    if not keep:
        keep = {scored[0][2]}
    return " ".join(sents[i] for i in sorted(keep))


def llm_compress(llm, text: str, query: str, budget: int = 700) -> Optional[str]:
    """LLM picks sentences; only sentences that literally occur in the source are kept (an LLM cannot inject text here)."""
    sys = f'Return the sentences of the passage that are relevant to the question, copied VERBATIM. JSON only: {{"sentences": ["..."]}}. {SYSTEM_GUARD}'
    try:
        j = parse_json(llm.complete(sys, f"Question: {neutralize(query)[:400]}\n{wrap_untrusted(text[:4000], 'passage')}"))
    except ProviderError:
        return None
    ss = (j or {}).get("sentences") if isinstance(j, dict) else None
    if not isinstance(ss, list):
        return None
    norm = " ".join(text.split())
    kept = [s.strip() for s in ss if isinstance(s, str) and s.strip() and " ".join(s.split()) in norm]
    return " ".join(kept)[: budget * 2] if kept else None


# ----------------------------------------------------------------------------- 6. corrective RAG grading
def grade_heuristic(hits: list[Hit], min_score: float) -> str:
    if not hits:
        return "incorrect"
    top = hits[0]
    if top.lexical >= 0.6 or top.score >= max(0.5, 1.6 * min_score):
        return "correct"
    return "ambiguous"


def grade_llm(llm, query: str, hits: list[Hit]) -> Optional[str]:
    if not hits:
        return "incorrect"
    sys = f'For each passage answer whether it contains information needed to answer the question. JSON only: {{"relevant": [true/false, ...]}}. {SYSTEM_GUARD}'
    top = hits[:3]
    body = "\n".join(f"[{i}] " + wrap_untrusted(h.text[:600], h.source) for i, h in enumerate(top))
    try:
        j = parse_json(llm.complete(sys, f"Question: {neutralize(query)[:400]}\n{body}"))
    except ProviderError:
        return None
    rel = (j or {}).get("relevant") if isinstance(j, dict) else None
    if not (isinstance(rel, list) and len(rel) == len(top)):
        return None
    n = sum(1 for r in rel if r is True)
    return "correct" if n and rel[0] is True else ("ambiguous" if n else "incorrect")


def reformulate(llm, query: str, attempt: int, rare_terms: list[str]) -> tuple[str, str]:
    if llm is not None and llm.available:
        sys = 'The previous search returned nothing relevant. Reformulate the question as a different search query (broader or with synonyms). JSON only: {"query": "..."}'
        try:
            j = parse_json(llm.complete(sys, neutralize(query)[:500]))
            q = (j or {}).get("query") if isinstance(j, dict) else None
            if isinstance(q, str) and 2 <= len(q) <= 300 and q.strip().lower() != query.lower():
                return q.strip(), "llm"
        except ProviderError:
            pass
    keep = rare_terms[: max(2, 5 - attempt)]  # fall back to the rarest (most discriminative) terms, progressively fewer
    return (" ".join(keep) if keep else query), "rare-terms"
