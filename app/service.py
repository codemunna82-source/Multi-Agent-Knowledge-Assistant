"""Ingestion facade: validate -> extract -> chunk -> embed -> index -> atomically commit."""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import Settings
from .core import IngestError, ProviderError, Unit
from .ingestion import web
from .ingestion.chunking import chunk_units
from .ingestion.loaders import TABULAR_KINDS, extract, kind_for
from .security.files import safe_filename, validate_upload
from .security.injection import scan_units
from .providers import LLM, Embedder, make_embedder, make_llm
from .storage import Scope, SessionStore, VectorBackend, make_backend, session_lock

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
        self.backend = backend or make_backend(settings.vector_store, settings.data_dir, settings)
        self.url_transport = url_transport
        self.stats = Stats()

    def store(self, scope: Scope) -> SessionStore:
        return SessionStore(self.settings.data_dir, scope)

    # ------------------------------------------------------------------ public API
    def ingest_file(self, scope: Scope, src: Path, filename: str, owner_id: str = "anonymous", visibility: str = "tenant", progress=None) -> dict:
        return self._guarded(filename, lambda: self._ingest(scope, uuid.uuid4().hex, filename, kind_for(filename), src_file=src, owner_id=owner_id, visibility=visibility, progress=progress))

    def ingest_url(self, scope: Scope, url: str, owner_id: str = "anonymous", visibility: str = "tenant", progress=None) -> dict:
        return self._guarded(url, lambda: self._ingest(scope, uuid.uuid4().hex, url, "url", url=url, owner_id=owner_id, visibility=visibility, progress=progress))

    def reindex(self, scope: Scope, source_id: str, principal=None, progress=None) -> dict:
        st = self.store(scope)
        meta = st.get_source(source_id, principal)
        if not meta:
            raise KeyError(source_id)
        keep = dict(created_at=meta["created_at"], owner_id=meta.get("owner_id", "anonymous"), visibility=meta.get("visibility", "tenant"), progress=progress)
        if meta["kind"] == "url":
            return self._guarded(meta["name"], lambda: self._ingest(scope, source_id, meta["name"], "url", url=meta["url"], **keep))
        orig = st.source_dir(source_id) / meta["original"]
        return self._guarded(meta["name"], lambda: self._ingest(scope, source_id, meta["name"], meta["kind"], src_file=orig, **keep))

    def delete(self, scope: Scope, source_id: str, principal=None) -> bool:
        """Removes text, chunks, vectors and the original file together. Hidden (ACL) sources behave as missing."""
        with session_lock(scope):
            st = self.store(scope)
            existed = st.get_source(source_id, principal) is not None
            if existed:
                self.backend.delete(st, source_id)
                st.delete(source_id)
            return existed

    # ------------------------------------------------------------------ internals
    def _guarded(self, name: str, fn) -> dict:
        try:
            meta = fn()
            self.stats.ingested += 1
            return {"status": "ready", "name": name, "source": meta, "error": None, "retryable": False}
        except IngestError as e:  # bad input: retrying cannot help
            self.stats.failed += 1
            log.warning("ingestion failed for %s: %s", name, e)
            return {"status": "failed", "name": name, "source": None, "error": str(e), "retryable": False}
        except ProviderError as e:  # embedding API outage / rate limit: transient
            self.stats.failed += 1
            log.warning("ingestion failed for %s: %s", name, e)
            return {"status": "failed", "name": name, "source": None, "error": str(e), "retryable": True}
        except Exception as e:  # never leak a stack trace to the client; keep it in logs
            self.stats.failed += 1
            log.exception("unexpected ingestion failure for %s", name)
            return {"status": "failed", "name": name, "source": None, "error": f"Unexpected error during ingestion: {type(e).__name__}", "retryable": True}

    def _ingest(self, scope: Scope, source_id: str, name: str, kind: str, *, src_file: Optional[Path] = None,
                url: Optional[str] = None, created_at: Optional[str] = None, owner_id: str = "anonymous",
                visibility: str = "tenant", progress=None) -> dict:
        s = self.settings
        st = self.store(scope)
        progress = progress or (lambda stage, pct: None)
        progress("extracting", 10)
        staging = st.staging_dir(source_id)
        try:
            meta: dict = {"id": source_id, "name": name, "kind": kind, "status": "ready", "created_at": created_at or _now(), "ingested_at": _now(),
                          "owner_id": owner_id, "visibility": visibility}
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
                validate_upload(orig, kind, s.max_zip_uncompressed_mb)
                ex = extract(orig, kind, s)
                if kind == "image":
                    self._caption_image(orig, ex)
                    if not ex.units:
                        raise IngestError("No text could be recognised in the image (and no captioning model is configured)")
                meta.update(original=orig.name, size_bytes=orig.stat().st_size, title=ex.title)
            flagged = scan_units(ex.units)
            if flagged:
                ex.warnings.append(f"{len(flagged)} passage(s) look like prompt-injection attempts and are treated strictly as data")
                meta["injection_flags"] = flagged[:200]
            progress("chunking", 40)
            chunks = chunk_units(ex.units, s.chunk_size, s.chunk_overlap)
            if not chunks:
                raise IngestError("No indexable content was extracted")
            records = [{"id": f"{source_id}:{i}", "text": c.text, "loc": c.loc, "loc_end": c.loc_end, "u0": c.u0, "u1": c.u1} for i, c in enumerate(chunks)]
            texts = [r["text"] for r in records]
            self.stats.embedded_chars += sum(map(len, texts))
            progress("embedding", 60)
            vectors = self.embedder.embed_documents(texts)
            if len(vectors) != len(records):
                raise ProviderError("Embedding provider returned an unexpected number of vectors")
            meta.update(
                units=len(ex.units), chunks=len(records), warnings=ex.warnings, embedding=self.embedder.name,
                tabular=kind in TABULAR_KINDS, **{k: v for k, v in ex.meta.items() if k in ("pages", "tables")},
            )
            progress("indexing", 85)
            with session_lock(scope):
                self.backend.delete(st, source_id)
                self.backend.add(st, staging, source_id, [r["id"] for r in records], vectors, texts)
                st.write_source(staging, meta, ex.units, records)
                if ex.tables:
                    (staging / "tables.json").write_text(json.dumps(ex.tables, ensure_ascii=False), encoding="utf-8")
                st.commit(staging, source_id)
            return meta
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _caption_image(self, path: Path, ex) -> None:
        """Multimodal: caption the image with a vision-capable LLM (opt-in, MKA_VISION_CAPTIONS=true)."""
        if not (self.settings.vision_captions and self.llm.available):
            return
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}.get(path.suffix.lower(), "image/png")
        try:
            cap = self.llm.describe_image(path.read_bytes(), mime, "Describe this image factually in 2-4 sentences. Transcribe any visible text. Do not speculate.")
        except ProviderError as e:
            ex.warnings.append(f"Image captioning failed: {e}")
            return
        if cap.strip():
            ex.units.append(Unit(cap.strip(), {"image": 1, "caption": True}))
