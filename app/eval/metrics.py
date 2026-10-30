"""Pure metric functions (unit-tested). Retrieval metrics follow standard binary-relevance IR definitions."""
from __future__ import annotations

import math
import re
from typing import Optional, Sequence

from ..core import stem, tokenize


def recall_at_k(matches: Sequence[set], k: int, n_gold: int) -> Optional[float]:
    """matches[i] = indexes of gold passages that retrieved item i satisfies. Fraction of gold passages found in the top k."""
    if n_gold == 0:
        return None
    found = set().union(*matches[:k]) if matches[:k] else set()
    return len(found) / n_gold


def precision_at_k(matches: Sequence[set], k: int) -> float:
    return sum(1 for m in matches[:k] if m) / k  # denominator is k: returning fewer than k results is penalised


def mrr(matches: Sequence[set]) -> float:
    for i, m in enumerate(matches, 1):
        if m:
            return 1.0 / i
    return 0.0


def ndcg_at_k(matches: Sequence[set], k: int, n_gold: int) -> Optional[float]:
    if n_gold == 0:
        return None
    seen: set = set()
    dcg = 0.0
    for i, m in enumerate(matches[:k], 1):
        gain = len(m - seen)
        seen |= m
        dcg += gain / math.log2(i + 1)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, n_gold) + 1))
    return dcg / ideal if ideal else None


def percentile(xs: Sequence[float], p: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    pos = (len(s) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def _content(s: str) -> list[str]:
    return [stem(t) for t in tokenize(re.sub(r"\[\d{1,2}\]", " ", s)) if not t.isdigit()]


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", re.sub(r"\[\d{1,2}\]", " ", s))}


def faithfulness_lexical(answer: str, evidence: str, threshold: float = 0.7) -> Optional[float]:
    """PROXY for faithfulness: share of answer sentences whose content words (and every number) occur in the cited evidence.
    Trivially ~1.0 for extractive answers; informative for LLM-generated ones. Use the LLM judge / RAGAS for semantic faithfulness."""
    answer = re.sub(r"^Most relevant passages found in the indexed sources:\s*", "", answer)
    answer = re.sub(r"\[[^\]]*(?:page|row|sheet|paragraph|line|table|path|section|http)[^\]]*\]", " ", answer)  # "[file, page 2]" location tags are not claims
    ev_tokens, ev_nums = set(_content(evidence)), _numbers(evidence)
    sents = [s.strip(" -•\t") for s in _SENT.split(answer) if len(s.strip()) > 3]
    scored = []
    for s in sents:
        toks = _content(s)
        if not toks:
            continue
        ok = sum(1 for t in toks if t in ev_tokens) / len(toks) >= threshold and _numbers(s) <= ev_nums
        scored.append(ok)
    return sum(scored) / len(scored) if scored else None


def answer_relevancy_embedding(embedder, question: str, answer: str) -> float:
    """PROXY for answer relevancy: cosine(question, answer) under the configured embedder, clipped to [0, 1]."""
    import numpy as np

    q, a = embedder.embed_query(question), embedder.embed_query(answer[:2000])
    d = float(np.linalg.norm(q) * np.linalg.norm(a))
    return max(0.0, min(1.0, float(q @ a) / d)) if d else 0.0
