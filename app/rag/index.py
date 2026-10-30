"""Per-(tenant, workspace) retrieval index: chunk records, inverted-index BM25, source metadata and flagged-unit sets.
Rebuilt lazily when the workspace changes (cheap signature check); unit text is cached for parent-child expansion."""
from __future__ import annotations

import math
import threading
from collections import Counter, OrderedDict
from datetime import datetime
from typing import Optional

from ..core import Unit, stem, tokenize
from ..storage import SessionStore
from .options import MetadataFilter


def terms(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text)]


class BM25:
    """Okapi BM25 with an inverted index (only documents containing a query term are touched)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.n = k1, b, len(docs)
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / self.n) if self.n else 1.0
        self.post: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.post.setdefault(t, []).append((i, f))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}
        self._by_prefix: dict[str, list[str]] = {}
        for t in self.post:
            self._by_prefix.setdefault(t[:5], []).append(t)

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in dict.fromkeys(query):
            for i, f in self.post.get(t, ()):
                out[i] = out.get(i, 0.0) + self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return out

    def expand(self, query: list[str], limit: int = 4) -> list[str]:
        """Fuzzy fallback: terms absent from the corpus are replaced by vocabulary terms sharing their 5-char prefix (inflections, typos)."""
        out = []
        for t in query:
            if t in self.post or len(t) < 5:
                out.append(t)
            else:
                out.extend(sorted(self._by_prefix.get(t[:5], []), key=lambda x: abs(len(x) - len(t)))[:limit] or [t])
        return out


class ScopeIndex:
    def __init__(self, st: SessionStore):
        self.chunks: list[dict] = []
        self.metas: dict[str, dict] = {}
        for meta in st.list_sources():
            self.metas[meta["id"]] = meta
            self.chunks.extend(st.load_chunks(meta["id"]))
        self.by_id = {c["id"]: c for c in self.chunks}
        self.pos = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.ch_terms = [terms(c["text"]) for c in self.chunks]
        self.bm25 = BM25(self.ch_terms)
        self.flagged: dict[str, set[int]] = {
            sid: {f["unit"] for f in m.get("injection_flags", [])} for sid, m in self.metas.items() if m.get("injection_flags")}

    def suspicious(self, chunk: dict) -> bool:
        f = self.flagged.get(chunk["id"].split(":", 1)[0])
        return bool(f) and any(chunk.get("u0", 0) <= u <= chunk.get("u1", 0) for u in f)

    def passes(self, flt: MetadataFilter, chunk: dict) -> bool:
        meta = self.metas[chunk["id"].split(":", 1)[0]]
        loc = chunk["loc"]
        if flt.kinds and meta.get("kind") not in flt.kinds:
            return False
        if flt.name_contains and flt.name_contains.lower() not in meta["name"].lower():
            return False
        page = loc.get("page")
        if flt.page_min is not None and (page is None or page < flt.page_min):
            return False
        if flt.page_max is not None and (page is None or page > flt.page_max):
            return False
        if flt.sheet and str(loc.get("sheet", "")).lower() != flt.sheet.lower():
            return False
        if flt.section_contains and flt.section_contains.lower() not in str(loc.get("section", "")).lower():
            return False
        ing = meta.get("ingested_at", "")
        for bound, cmp in ((flt.ingested_after, lambda a, b: a >= b), (flt.ingested_before, lambda a, b: a <= b)):
            if bound:
                try:
                    if not cmp(datetime.fromisoformat(ing), datetime.fromisoformat(bound if "T" in bound else bound + "T00:00:00+00:00")):
                        return False
                except ValueError:
                    return False
        return True


class IndexCache:
    def __init__(self):
        self._idx: dict[str, tuple] = {}
        self._units: "OrderedDict[tuple, list[Unit]]" = OrderedDict()
        self._lock = threading.Lock()

    def index(self, st: SessionStore) -> ScopeIndex:
        ver = st.version()
        with self._lock:
            hit = self._idx.get(st.session)
            if hit and hit[0] == ver:
                return hit[1]
        idx = ScopeIndex(st)
        with self._lock:
            self._idx[st.session] = (ver, idx)
        return idx

    def units(self, st: SessionStore, source_id: str) -> list[Unit]:
        mt = (st.source_dir(source_id) / "meta.json").stat().st_mtime_ns
        key = (st.session, source_id, mt)
        with self._lock:
            if key in self._units:
                self._units.move_to_end(key)
                return self._units[key]
        units = [u for _, u in st.iter_units([source_id])]
        with self._lock:
            self._units[key] = units
            while len(self._units) > 64:
                self._units.popitem(last=False)
        return units
