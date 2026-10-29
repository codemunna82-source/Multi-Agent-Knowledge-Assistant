"""On-disk registry (one directory per session, one sub-directory per source) and vector backends.

    data/sessions/<session>/sources/<source_id>/
        meta.json  units.jsonl  chunks.jsonl  vectors.npy  original.<ext>

Deleting a source removes its directory, so text, chunks and (local) vectors disappear together.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

from .core import Unit

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def session_lock(session: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(session, threading.RLock())


class SessionStore:
    def __init__(self, data_dir: str | Path, session: str):
        if not SESSION_RE.match(session):
            raise ValueError("Invalid session id (use 1-64 letters, digits, '-' or '_')")
        self.session = session
        self.root = Path(data_dir) / "sessions" / session
        self.sources_dir = self.root / "sources"
        self.sources_dir.mkdir(parents=True, exist_ok=True)

    # -- paths
    def source_dir(self, source_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", source_id):
            raise KeyError(source_id)
        return self.sources_dir / source_id

    def staging_dir(self, source_id: str) -> Path:
        d = self.sources_dir / f".tmp-{source_id}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        return d

    # -- writes
    @staticmethod
    def write_source(d: Path, meta: dict, units: list[Unit], chunks: list[dict]) -> None:
        with open(d / "units.jsonl", "w", encoding="utf-8") as f:
            for u in units:
                f.write(json.dumps({"text": u.text, "loc": u.loc}, ensure_ascii=False) + "\n")
        with open(d / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def commit(self, staging: Path, source_id: str) -> None:
        """Atomically replace/create the source directory (staging is complete at this point)."""
        final = self.source_dir(source_id)
        old = None
        if final.exists():
            old = self.sources_dir / f".old-{source_id}"
            shutil.rmtree(old, ignore_errors=True)
            final.rename(old)
        staging.rename(final)
        if old:
            shutil.rmtree(old, ignore_errors=True)

    def delete(self, source_id: str) -> bool:
        d = self.source_dir(source_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True

    # -- reads
    def list_sources(self) -> list[dict]:
        out = []
        for d in sorted(self.sources_dir.iterdir()):
            if d.name.startswith(".") or not (d / "meta.json").exists():
                continue
            out.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
        return sorted(out, key=lambda m: m.get("created_at", ""))

    def get_source(self, source_id: str) -> Optional[dict]:
        try:
            p = self.source_dir(source_id) / "meta.json"
        except KeyError:
            return None
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def iter_units(self, source_ids: Optional[list[str]] = None) -> Iterator[tuple[dict, Unit]]:
        for meta in self.list_sources():
            if source_ids is not None and meta["id"] not in source_ids:
                continue
            with open(self.source_dir(meta["id"]) / "units.jsonl", encoding="utf-8") as f:
                for line in f:
                    j = json.loads(line)
                    yield meta, Unit(j["text"], j["loc"])

    def load_chunks(self, source_id: str) -> list[dict]:
        with open(self.source_dir(source_id) / "chunks.jsonl", encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def version(self) -> tuple:
        """Cheap change signature used to invalidate in-memory indexes."""
        sig = []
        for d in sorted(self.sources_dir.iterdir()):
            m = d / "meta.json"
            if not d.name.startswith(".") and m.exists():
                sig.append((d.name, m.stat().st_mtime_ns))
        return tuple(sig)

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- vector backends
class VectorBackend:
    def add(self, store: SessionStore, staging: Path, source_id: str, chunk_ids: list[str], vectors: np.ndarray, texts: list[str]) -> None: ...
    def delete(self, store: SessionStore, source_id: str) -> None: ...
    def search(self, store: SessionStore, qvec: np.ndarray, k: int, source_ids: Optional[list[str]], embedding: str) -> list[tuple[str, float]]: ...


class LocalVectors(VectorBackend):
    """Vectors live inside each source directory; search is exact cosine over a cached matrix."""

    def __init__(self):
        self._cache: dict[str, tuple] = {}
        self._guard = threading.Lock()

    def add(self, store, staging, source_id, chunk_ids, vectors, texts):
        np.save(staging / "vectors.npy", vectors.astype(np.float32))

    def delete(self, store, source_id):
        pass  # vectors are removed together with the source directory

    def _matrix(self, store: SessionStore, embedding: str):
        ver = (store.version(), embedding)
        with self._guard:
            hit = self._cache.get(store.session)
            if hit and hit[0] == ver:
                return hit[1], hit[2]
        ids: list[str] = []
        mats = []
        for meta in store.list_sources():
            vp = store.source_dir(meta["id"]) / "vectors.npy"
            if meta.get("embedding") != embedding or not vp.exists():
                continue
            m = np.load(vp)
            cids = [c["id"] for c in store.load_chunks(meta["id"])]
            if len(cids) == len(m):
                ids.extend(cids)
                mats.append(m)
        mat = np.vstack(mats) if mats else np.zeros((0, 1), dtype=np.float32)
        with self._guard:
            self._cache[store.session] = (ver, mat, ids)
        return mat, ids

    def search(self, store, qvec, k, source_ids, embedding):
        mat, ids = self._matrix(store, embedding)
        if not len(ids):
            return []
        scores = mat @ qvec.astype(np.float32)
        if source_ids is not None:
            allowed = set(source_ids)
            mask = np.array([cid.split(":", 1)[0] in allowed for cid in ids])
            scores = np.where(mask, scores, -np.inf)
        order = np.argsort(-scores)[:k]
        return [(ids[i], float(scores[i])) for i in order if np.isfinite(scores[i])]


class ChromaVectors(VectorBackend):
    """ChromaDB persistent collection per session (cosine). Embeddings are supplied by our embedder."""

    def __init__(self, data_dir: str | Path):
        import chromadb

        self.client = chromadb.PersistentClient(path=str(Path(data_dir) / "chroma"))

    def _col(self, store: SessionStore):
        return self.client.get_or_create_collection(f"mka_{store.session}", metadata={"hnsw:space": "cosine"})

    def add(self, store, staging, source_id, chunk_ids, vectors, texts):
        col = self._col(store)
        for i in range(0, len(chunk_ids), 500):
            col.add(
                ids=chunk_ids[i : i + 500],
                embeddings=vectors[i : i + 500].tolist(),
                documents=texts[i : i + 500],
                metadatas=[{"source_id": source_id}] * len(chunk_ids[i : i + 500]),
            )

    def delete(self, store, source_id):
        self._col(store).delete(where={"source_id": source_id})

    def search(self, store, qvec, k, source_ids, embedding):
        col = self._col(store)
        if col.count() == 0:
            return []
        valid = [m["id"] for m in store.list_sources() if m.get("embedding") == embedding]
        if source_ids is not None:
            valid = [v for v in valid if v in source_ids]
        if not valid:
            return []
        r = col.query(query_embeddings=[qvec.tolist()], n_results=min(k, col.count()), where={"source_id": {"$in": valid}})
        return [(i, 1.0 - d) for i, d in zip(r["ids"][0], r["distances"][0])]


def make_backend(kind: str, data_dir: str | Path) -> VectorBackend:
    if kind == "local":
        return LocalVectors()
    if kind == "chroma":
        return ChromaVectors(data_dir)
    raise ValueError(f"Unknown vector store '{kind}'")
