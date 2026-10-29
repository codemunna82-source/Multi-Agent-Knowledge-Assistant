"""Hybrid retrieval: vector search + BM25, fused with reciprocal rank fusion, then a relevance gate
so that unrelated questions return NO evidence rather than the 'least bad' chunks."""
from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from ..core import format_loc, stem, tokenize


@dataclass
class Hit:
    chunk_id: str
    source_id: str
    source: str
    location: str
    loc: dict
    text: str
    score: float  # cosine similarity (0 if only found lexically)
    lexical: float  # fraction of query terms present in the chunk


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = [Counter(d) for d in docs]
        self.avg = (sum(map(len, docs)) / len(docs)) if docs else 1.0
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in query:
                f = tf.get(t)
                if f:
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


class Retriever:
    def __init__(self, knowledge):
        self.k = knowledge
        self._cache: dict[str, tuple] = {}
        self._guard = threading.Lock()

    def _lexical_index(self, st):
        ver = st.version()
        with self._guard:
            hit = self._cache.get(st.session)
            if hit and hit[0] == ver:
                return hit[1], hit[2], hit[3]
        chunks, names = [], {}
        for meta in st.list_sources():
            names[meta["id"]] = meta["name"]
            chunks.extend(st.load_chunks(meta["id"]))
        bm = BM25([[stem(t) for t in tokenize(c["text"])] for c in chunks])
        with self._guard:
            self._cache[st.session] = (ver, chunks, bm, names)
        return chunks, bm, names

    def search(self, session: str, query: str, k: int = 6, source_ids: Optional[list[str]] = None) -> list[Hit]:
        st = self.k.store(session)
        chunks, bm, names = self._lexical_index(st)
        if not chunks:
            return []
        by_id = {c["id"]: c for c in chunks}
        allowed = set(source_ids) if source_ids is not None else None
        q_tokens = [stem(t) for t in tokenize(query)]
        pool = max(k * 4, 20)

        vec = self.k.backend.search(st, self.k.embedder.embed_query(query), pool, source_ids, self.k.embedder.name)
        cos = dict(vec)
        lex_scores = bm.scores(q_tokens) if q_tokens else [0.0] * len(chunks)
        lex_rank = [chunks[i]["id"] for i in sorted(range(len(chunks)), key=lambda i: -lex_scores[i])
                    if lex_scores[i] > 0 and (allowed is None or chunks[i]["id"].split(":", 1)[0] in allowed)][:pool]

        fused: dict[str, float] = {}
        for rank_list in ([cid for cid, _ in vec], lex_rank):
            for r, cid in enumerate(rank_list):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + r)

        min_score = self.k.settings.effective_min_score
        qset = set(q_tokens)
        hits: list[Hit] = []
        for cid, _ in sorted(fused.items(), key=lambda kv: -kv[1]):
            c = by_id.get(cid)
            if not c:
                continue
            ctoks = {stem(t) for t in tokenize(c["text"])}
            overlap = len(qset & ctoks) / len(qset) if qset else 0.0
            score = cos.get(cid, 0.0)
            if score < min_score and overlap < 0.5:  # relevance gate
                continue
            sid = cid.split(":", 1)[0]
            hits.append(Hit(cid, sid, names[sid], format_loc(c["loc"], c.get("loc_end")), c["loc"], c["text"], score, overlap))
            if len(hits) >= k:
                break
        return hits
