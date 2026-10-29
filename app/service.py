"""Ingestion facade: validate -> extract -> chunk -> embed -> index -> atomically commit."""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import Settings
from .core import IngestError, ProviderError
from .ingestion import web
from .ingestion.chunking import chunk_units
from .ingestion.loaders import TABULAR_KINDS, extract, kind_for
from .providers import LLM, Embedder, make_embedder, make_llm
from .storage import SessionStore, VectorBackend, make_backend, session_lock

log = logging.getLogger("mka.ingest")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Stats:
    def __init__(self):
        self.ingested = self.failed = self.questions = self.embedded_chars = 0


class Knowledge:
    def __init__(self, settings: Settings, embedder: Optional[Embedder] = None, llm: Optional[LLM] = None,
                 backend: Optional[VectorBackend] = None, url_transport: Optional[httpx.BaseTransport] = None):
        self.settings = settings
        self.embedder = embedder or make_embedder(settings)
        self.llm = llm or make_llm(settings)
        self.backend = backend or make_backend(settings.vector_store, settings.data_dir)
        self.url_transport = url_transport
        self.stats = Stats()

    def store(self, session: str) -> SessionStore:
        return SessionStore(self.settings.data_dir, session)

    # ------------------------------------------------------------------ public API
    def ingest_file(self, session: str, src: Path, filename: str) -> dict:
        return self._guarded(filename, lambda: self._ingest(session, uuid.uuid4().hex, filename, kind_for(filename), src_file=src))

    def ingest_url(self, session: str, url: str) -> dict:
        return self._guarded(url, lambda: self._ingest(session, uuid.uuid4().hex, url, "url", url=url))

    def reindex(self, session: str, source_id: str) -> dict:
        st = self.store(session)
        meta = st.get_source(source_id)
        if not meta:
            raise KeyError(source_id)
        if meta["kind"] == "url":
            return self._guarded(meta["name"], lambda: self._ingest(session, source_id, meta["name"], "url", url=meta["url"], created_at=meta["created_at"]))
        orig = st.source_dir(source_id) / meta["original"]
        return self._guarded(meta["name"], lambda: self._ingest(session, source_id, meta["name"], meta["kind"], src_file=orig, created_at=meta["created_at"]))

    def delete(self, session: str, source_id: str) -> bool:
        with session_lock(session):
            st = self.store(session)
            existed = st.get_source(source_id) is not None
            self.backend.delete(st, source_id)
            st.delete(source_id)
            return existed

    # ------------------------------------------------------------------ internals
    def _guarded(self, name: str, fn) -> dict:
        try:
            meta = fn()
            self.stats.ingested += 1
            return {"status": "ready", "name": name, "source": meta, "error": None}
        except (IngestError, ProviderError) as e:
            self.stats.failed += 1
            log.warning("ingestion failed for %s: %s", name, e)
            return {"status": "failed", "name": name, "source": None, "error": str(e)}
        except Exception as e:  # never leak a stack trace to the client; keep it in logs
            self.stats.failed += 1
            log.exception("unexpected ingestion failure for %s", name)
            return {"status": "failed", "name": name, "source": None, "error": f"Unexpected error during ingestion: {type(e).__name__}"}

    def _ingest(self, session: str, source_id: str, name: str, kind: str, *, src_file: Optional[Path] = None,
                url: Optional[str] = None, created_at: Optional[str] = None) -> dict:
        s = self.settings
        st = self.store(session)
        staging = st.staging_dir(source_id)
        try:
            meta: dict = {"id": source_id, "name": name, "kind": kind, "status": "ready", "created_at": created_at or _now(), "ingested_at": _now()}
            if kind == "url":
                final_url, ctype, body = web.fetch(url, s, self.url_transport)
                ex = web.extract_html(final_url, ctype, body)
                (staging / "original.html").write_text(body, encoding="utf-8")
                meta.update(url=url, final_url=final_url, original="original.html", size_bytes=len(body.encode()), title=ex.title, canonical_link=ex.meta.get("canonical_link"))
            else:
                ext = Path(name).suffix.lower()
                orig = staging / f"original{ext}"
                if src_file.resolve() != orig.resolve():
                    shutil.copyfile(src_file, orig)
                ex = extract(orig, kind, s.ocr_enabled)
                meta.update(original=orig.name, size_bytes=orig.stat().st_size, title=ex.title)
            chunks = chunk_units(ex.units, s.chunk_size, s.chunk_overlap)
            if not chunks:
                raise IngestError("No indexable content was extracted")
            records = [{"id": f"{source_id}:{i}", "text": c.text, "loc": c.loc, "loc_end": c.loc_end} for i, c in enumerate(chunks)]
            texts = [r["text"] for r in records]
            self.stats.embedded_chars += sum(map(len, texts))
            vectors = self.embedder.embed_documents(texts)
            if len(vectors) != len(records):
                raise ProviderError("Embedding provider returned an unexpected number of vectors")
            meta.update(
                units=len(ex.units), chunks=len(records), warnings=ex.warnings, embedding=self.embedder.name,
                tabular=kind in TABULAR_KINDS, **{k: v for k, v in ex.meta.items() if k in ("pages", "tables")},
            )
            with session_lock(session):
                self.backend.delete(st, source_id)
                self.backend.add(st, staging, source_id, [r["id"] for r in records], vectors, texts)
                st.write_source(staging, meta, ex.units, records)
                st.commit(staging, source_id)
            return meta
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
