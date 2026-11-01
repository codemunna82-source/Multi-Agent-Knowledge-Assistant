"""Ingestion facade: validate -> extract -> chunk -> embed -> index -> atomically commit."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

from .config import Settings
from .db import Database
from .core import IngestError, ProviderError, Unit
from .ingestion import web
from .ingestion.chunking import chunk_units
from .ingestion.loaders import TABULAR_KINDS, extract, kind_for
from .intel.classify import classify
from .intel.entities import chunk_entities, chunk_relations
from .intel.language import detect_language
from .security.files import validate_upload
from .security.injection import scan_units
from .providers import LLM, Embedder, make_embedder, make_llm
from .observability import Observability
from .registry import Registry
from .storage import Scope, SessionStore, VectorBackend, make_backend, session_lock

log = logging.getLogger("mka.ingest")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Duplicate(Exception):
    """The identical file/page is already indexed in this workspace (not an error: reported to the caller)."""

    def __init__(self, existing: dict):
        super().__init__(f"duplicate of {existing.get('name')}")
        self.existing = existing


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def text_digest(units) -> str:
    """Hash of the normalised extracted text: identifies 'same content, different bytes' (re-saved PDF, re-fetched page)."""
    h = hashlib.sha256()
    for u in units:
        h.update(re.sub(r"\s+", " ", u.text.lower()).strip().encode())
        h.update(b"\n")
    return h.hexdigest()


class Stats:
    def __init__(self):
        self.ingested = self.failed = self.questions = self.embedded_chars = 0


class Knowledge:
    def __init__(self, settings: Settings, embedder: Optional[Embedder] = None, llm: Optional[LLM] = None,
                 backend: Optional[VectorBackend] = None, url_transport: Optional[httpx.BaseTransport] = None, db: Optional[Database] = None):
        self.settings = settings
        self.db = db or Database(settings.db_url)
        self.registry = Registry(self.db)
        self.embedder = embedder or make_embedder(settings)
        self.llm = llm or make_llm(settings)
        self.backend = backend or make_backend(settings.vector_store, settings.data_dir, settings)
        self.url_transport = url_transport
        self.stats = Stats()
        self.obs = Observability(settings)

    def store(self, scope: Scope) -> SessionStore:
        return SessionStore(self.settings.data_dir, scope, self.registry)

    # ------------------------------------------------------------------ public API
    def ingest_file(self, scope: Scope, src: Path, filename: str, owner_id: str = "anonymous", visibility: str = "tenant", progress=None,
                    allow_duplicate: Optional[bool] = None) -> dict:
        allow = self.settings.allow_duplicate_uploads if allow_duplicate is None else allow_duplicate
        return self._guarded(filename, lambda: self._ingest_and_alert(scope, uuid.uuid4().hex, filename, kind_for(filename), src_file=src, owner_id=owner_id, visibility=visibility,
                                                            progress=progress, allow_duplicate=allow, content_hash=sha256_file(src)))

    def ingest_url(self, scope: Scope, url: str, owner_id: str = "anonymous", visibility: str = "tenant", progress=None, allow_duplicate: Optional[bool] = None) -> dict:
        allow = self.settings.allow_duplicate_uploads if allow_duplicate is None else allow_duplicate
        return self._guarded(url, lambda: self._ingest_and_alert(scope, uuid.uuid4().hex, url, "url", url=url, owner_id=owner_id, visibility=visibility, progress=progress, allow_duplicate=allow))

    def reindex(self, scope: Scope, source_id: str, principal=None, progress=None) -> dict:
        """Rebuild the text/chunks/vectors of an existing version in place (same id, same version number)."""
        st = self.store(scope)
        meta = st.get_source(source_id, principal)
        if not meta:
            raise KeyError(source_id)
        keep = dict(created_at=meta["created_at"], owner_id=meta.get("owner_id", "anonymous"), visibility=meta.get("visibility", "tenant"), progress=progress,
                    doc_key=meta.get("doc_key", source_id), version=meta.get("version", 1), allow_duplicate=True, is_reindex=True, content_hash=meta.get("content_hash"))
        if meta["kind"] == "url":
            return self._guarded(meta["name"], lambda: self._ingest(scope, source_id, meta["name"], "url", url=meta["url"], **keep))
        orig = st.source_dir(source_id) / meta["original"]
        return self._guarded(meta["name"], lambda: self._ingest(scope, source_id, meta["name"], meta["kind"], src_file=orig, **keep))

    def _purge_version(self, scope: Scope, source_id: str) -> Optional[dict]:
        st = self.store(scope)
        self.backend.delete(st, source_id)
        st.delete(source_id)
        return self.registry.remove(scope, source_id)

    def delete(self, scope: Scope, source_id: str, principal=None, all_versions: bool = False) -> bool:
        """Removes text, chunks, vectors, original file and registry row. Deleting the current version of a document that has older versions
        restores the newest older version (all_versions=True removes the whole document). Hidden (ACL) sources behave as missing."""
        with session_lock(scope):
            st = self.store(scope)
            meta = st.get_source(source_id, principal)
            if meta is None:
                return False
            ids = [source_id]
            if all_versions:
                ids = [v["id"] for v in self.registry.versions(scope, meta.get("doc_key", source_id))] or ids
            for i in ids:
                self._purge_version(scope, i)
            return True

    # ------------------------------------------------------------------ internals
    def _guarded(self, name: str, fn) -> dict:
        t0 = time.perf_counter()
        out = self._guarded_inner(name, fn)
        m = self.obs.metrics
        m.ingest.labels(out["status"]).inc()
        m.ingest_seconds.observe(time.perf_counter() - t0)
        return out

    def _ingest_and_alert(self, scope: Scope, *a, **kw) -> dict:
        """_ingest + saved-search alerts for the new document (a failure in the alerting never fails the ingestion)."""
        meta = self._ingest(scope, *a, **kw)
        try:
            from . import automation

            automation.on_ingested(self, scope, meta)
        except Exception:  # noqa: BLE001
            log.exception("post-ingest automation failed for %s", meta.get("name"))
        return meta

    def _guarded_inner(self, name: str, fn) -> dict:
        try:
            meta = fn()
            self.stats.ingested += 1

            return {"status": "ready", "name": name, "source": meta, "error": None, "retryable": False}
        except Duplicate as d:
            return {"status": "duplicate", "name": name, "source": d.existing, "error": None, "retryable": False, "duplicate_of": d.existing["id"]}
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

    def _guarded_inner(self, name: str, fn) -> dict:
        try:
            meta = fn()
            self.stats.ingested += 1
            return {"status": "ready", "name": name, "source": meta, "error": None, "retryable": False}
        except Duplicate as d:
            return {"status": "duplicate", "name": name, "source": d.existing, "error": None, "retryable": False, "duplicate_of": d.existing["id"]}
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

    def _identity(self, scope: Scope, name: str, content_hash: Optional[str], allow_duplicate: bool):
        """-> (doc_key, version, previous_current_meta). Raises Duplicate for an identical file already indexed in the workspace."""
        if content_hash and not allow_duplicate:
            dup = self.registry.find_by_hash(scope, content_hash)
            if dup:
                raise Duplicate(dup)
        cur = self.registry.current_by_name(scope, name)
        if cur:
            top = self.registry.versions(scope, cur["doc_key"])[0]["version"]
            return cur["doc_key"], top + 1, cur
        return None, 1, None

    def _ingest(self, scope: Scope, source_id: str, name: str, kind: str, *, src_file: Optional[Path] = None,
                url: Optional[str] = None, created_at: Optional[str] = None, owner_id: str = "anonymous",
                visibility: str = "tenant", progress=None, allow_duplicate: bool = False, content_hash: Optional[str] = None,
                doc_key: Optional[str] = None, version: int = 1, is_reindex: bool = False) -> dict:
        s = self.settings
        st = self.store(scope)
        progress = progress or (lambda stage, pct: None)
        previous = None
        if not is_reindex and kind != "url":  # URLs are de-duplicated by extracted text below (the fetched bytes change on every request)
            doc_key, version, previous = self._identity(scope, name, content_hash, allow_duplicate)
        progress("extracting", 10)
        staging = st.staging_dir(source_id)
        try:
            meta: dict = {"id": source_id, "name": name, "kind": kind, "status": "ready", "created_at": created_at or _now(), "ingested_at": _now(),
                          "owner_id": owner_id, "visibility": visibility, "content_hash": content_hash}
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
                ex = extract(orig, kind, s, on_page=lambda i, n: progress("extracting", 10 + int(25 * i / max(n, 1))) if i % 25 == 0 or i == n else None)
                if kind == "image":
                    self._caption_image(orig, ex)
                    if not ex.units:
                        raise IngestError("No text could be recognised in the image (and no captioning model is configured)")
                meta.update(original=orig.name, size_bytes=orig.stat().st_size, title=ex.title)
            meta["text_hash"] = text_digest(ex.units)
            if kind == "url":
                meta["content_hash"] = meta["text_hash"]
                if not is_reindex:
                    doc_key, version, previous = self._identity(scope, name, meta["content_hash"], allow_duplicate)
            same_text = self.registry.find_by_text_hash(scope, meta["text_hash"], exclude_id=source_id)
            if same_text and not is_reindex and (previous is None or same_text["id"] != previous["id"]):
                ex.warnings.append(f"The extracted text is identical to '{same_text['name']}' (different file bytes)")
            meta["doc_key"], meta["version"] = doc_key or source_id, version
            flagged = scan_units(ex.units)
            if flagged:
                ex.warnings.append(f"{len(flagged)} passage(s) look like prompt-injection attempts and are treated strictly as data")
                meta["injection_flags"] = flagged[:200]
            progress("chunking", 40)
            chunks = chunk_units(ex.units, s.chunk_size, s.chunk_overlap, structure=s.chunk_strategy == "structure")
            if not chunks:
                raise IngestError("No indexable content was extracted")
            records = [{"id": f"{source_id}:{i}", "text": c.text, "loc": c.loc, "loc_end": c.loc_end, "u0": c.u0, "u1": c.u1} for i, c in enumerate(chunks)]
            texts = [r["text"] for r in records]
            self.stats.embedded_chars += sum(map(len, texts))
            progress("embedding", 60)
            B, parts = max(1, s.embed_batch), []
            for i in range(0, len(texts), B):  # batches keep memory flat on 1,000+ page documents and give the progress bar something to show
                parts.append(self.embedder.embed_documents(texts[i:i + B]))
                progress("embedding", 60 + int(25 * min(i + B, len(texts)) / len(texts)))
            vectors = np.vstack(parts) if parts else np.zeros((0, 1), dtype=np.float32)
            if len(vectors) != len(records):
                raise ProviderError("Embedding provider returned an unexpected number of vectors")
            meta["language"] = detect_language(" ".join(u.text for u in ex.units[:40]))
            meta["classification"] = classify(kind, name, ex.units, self.llm if self.llm.available else None)
            if ex.meta.get("properties"):
                meta["properties"] = ex.meta["properties"]
            if ex.meta.get("engine"):
                meta["engine"] = ex.meta["engine"]
            meta.update(
                units=len(ex.units), chunks=len(records), warnings=ex.warnings, embedding=self.embedder.name,
                tabular=kind in TABULAR_KINDS, **{k: v for k, v in ex.meta.items() if k in ("pages", "tables")},
            )
            progress("indexing", 85)
            with session_lock(scope):
                if not is_reindex and not allow_duplicate and meta.get("content_hash"):  # re-check under the lock: two concurrent uploads of the same file
                    dup = self.registry.find_by_hash(scope, meta["content_hash"])
                    if dup:
                        raise Duplicate(dup)
                self.backend.delete(st, source_id)
                self.backend.add(st, staging, source_id, [r["id"] for r in records], vectors, texts)
                st.write_source(staging, meta, ex.units, records)
                (staging / "graph.json").write_text(json.dumps({r["id"]: chunk_entities(r["text"]) for r in records if r["text"]}, ensure_ascii=False), encoding="utf-8")
                rels = {r["id"]: chunk_relations(r["text"]) for r in records if r["text"]}
                (staging / "relations.json").write_text(json.dumps({k: v for k, v in rels.items() if v}, ensure_ascii=False), encoding="utf-8")
                if ex.tables:
                    (staging / "tables.json").write_text(json.dumps(ex.tables, ensure_ascii=False), encoding="utf-8")
                st.commit(staging, source_id)
                try:
                    self.registry.register(scope, meta)
                except Exception:  # registry is the source of truth: do not leave an unregistered, unsearchable directory behind
                    self.backend.delete(st, source_id)
                    st.delete(source_id)
                    raise
                for old in self.registry.versions(scope, meta["doc_key"])[s.max_versions_per_document:]:
                    if not old["is_current"]:
                        self._purge_version(scope, old["id"])
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
