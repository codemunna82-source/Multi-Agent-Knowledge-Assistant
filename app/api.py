from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .agent import Assistant
from .config import Settings, get_settings
from .core import ProviderError
from .schemas import AskRequest, AskResponse, IngestResult, SourceInfo, UrlRequest
from .service import Knowledge
from .storage import SESSION_RE, session_lock

log = logging.getLogger("mka")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k in ("request_id", "session", "path", "status", "ms"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger("mka")
    if not root.handlers:
        root.addHandler(h)
    root.setLevel(logging.INFO)


def create_app(settings: Optional[Settings] = None, knowledge: Optional[Knowledge] = None) -> FastAPI:
    setup_logging()
    settings = settings or get_settings()
    k = knowledge or Knowledge(settings)
    assistant = Assistant(k)

    app = FastAPI(title="Multi-Agent Knowledge Assistant", version="1.0.0",
                  description="Upload documents or URLs, then ask questions and get answers with verifiable citations.")
    app.state.knowledge, app.state.assistant = k, assistant

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": rid, "path": request.url.path})
            resp = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        resp.headers["X-Request-ID"] = rid
        log.info("request", extra={"request_id": rid, "path": request.url.path, "status": resp.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return resp

    def session_id(x_session_id: str = Header(default="default")) -> str:
        if not SESSION_RE.match(x_session_id):
            raise HTTPException(400, "Invalid X-Session-ID (1-64 letters, digits, '-' or '_')")
        return x_session_id

    def info(meta: dict) -> SourceInfo:
        d = {**meta, "tables": meta.get("tables")}
        d["needs_reindex"] = meta.get("embedding") != k.embedder.name
        return SourceInfo(**{f: d.get(f) for f in SourceInfo.model_fields if f in d})

    @app.get("/health", tags=["system"])
    def health():
        s = k.stats
        return {"status": "ok", "embedder": k.embedder.name, "llm": k.llm.name, "vector_store": settings.vector_store,
                "usage": {"ingested": s.ingested, "failed": s.failed, "questions": s.questions, "embedded_chars": s.embedded_chars, "llm_calls": k.llm.calls}}

    @app.post("/sources/upload", response_model=list[IngestResult], tags=["sources"])
    def upload(files: list[UploadFile] = File(...), session: str = Depends(session_id)):
        limit = settings.max_upload_mb * 1024 * 1024
        results = []
        for f in files:
            name = Path(f.filename or "upload").name
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "upload.bin"
                size, too_big = 0, False
                with open(path, "wb") as out:
                    while chunk := f.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            too_big = True
                            break
                        out.write(chunk)
                if too_big:
                    results.append(IngestResult(status="failed", name=name, error=f"File exceeds the {settings.max_upload_mb} MB limit"))
                elif size == 0:
                    results.append(IngestResult(status="failed", name=name, error="The file is empty"))
                else:
                    r = k.ingest_file(session, path, name)
                    results.append(IngestResult(status=r["status"], name=name, error=r["error"], source=info(r["source"]) if r["source"] else None))
        return results

    @app.post("/sources/url", response_model=IngestResult, tags=["sources"])
    def add_url(body: UrlRequest, session: str = Depends(session_id)):
        r = k.ingest_url(session, body.url)
        return IngestResult(status=r["status"], name=body.url, error=r["error"], source=info(r["source"]) if r["source"] else None)

    @app.get("/sources", response_model=list[SourceInfo], tags=["sources"])
    def list_sources(session: str = Depends(session_id)):
        return [info(m) for m in k.store(session).list_sources()]

    @app.get("/sources/{source_id}", response_model=SourceInfo, tags=["sources"])
    def get_source(source_id: str, session: str = Depends(session_id)):
        m = k.store(session).get_source(source_id)
        if not m:
            raise HTTPException(404, "Source not found")
        return info(m)

    @app.post("/sources/{source_id}/reindex", response_model=IngestResult, tags=["sources"])
    def reindex(source_id: str, session: str = Depends(session_id)):
        try:
            r = k.reindex(session, source_id)
        except KeyError:
            raise HTTPException(404, "Source not found")
        return IngestResult(status=r["status"], name=r["name"], error=r["error"], source=info(r["source"]) if r["source"] else None)

    @app.delete("/sources/{source_id}", tags=["sources"])
    def delete_source(source_id: str, session: str = Depends(session_id)):
        try:
            if not k.delete(session, source_id):
                raise HTTPException(404, "Source not found")
        except KeyError:
            raise HTTPException(404, "Source not found")
        return {"deleted": source_id}

    @app.post("/ask", response_model=AskResponse, tags=["chat"])
    def ask(body: AskRequest, request: Request, session: str = Depends(session_id)):
        try:
            resp = assistant.ask(session, body)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0]))
        except ProviderError as e:
            raise HTTPException(502, f"Model/API error: {e}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Upstream error: {e}")
        resp.request_id = request.state.request_id
        return resp

    @app.delete("/session", tags=["chat"])
    def clear_session(session: str = Depends(session_id)):
        """Delete ALL sources and conversation history of the calling session."""
        with session_lock(session):
            for m in k.store(session).list_sources():
                k.backend.delete(k.store(session), m["id"])
            k.store(session).clear()
            assistant.history.pop(session, None)
        return {"cleared": session}

    return app
