from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..agents import Assistant
from ..config import Settings, get_settings
from ..db import Database
from ..jobs import JobService
from ..security.audit import Auditor
from ..security.ratelimit import RateLimiter
from ..service import Knowledge
from .deps import Ctx, Services, get_principal, require
from .routers import admin, analytics, auth, chat, feedback, features, learn, memory, reports, evaluation, intel, jobs, sources

log = logging.getLogger("mka")
STATIC = Path(__file__).resolve().parent.parent / "static"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k in ("request_id", "path", "status", "ms", "tenant"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging() -> None:
    root = logging.getLogger("mka")
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
    root.setLevel(logging.INFO)


def make_redis(settings: Settings):
    if not settings.redis_url:
        return None
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=False)


def create_app(settings: Optional[Settings] = None, knowledge: Optional[Knowledge] = None, db: Optional[Database] = None, redis_client=None) -> FastAPI:
    setup_logging()
    settings = settings or get_settings()
    settings.validate_production()
    db = db or (knowledge.db if knowledge is not None else Database(settings.db_url, run_migrations=settings.env == "production" or settings.auto_migrate))
    k = knowledge or Knowledge(settings, db=db)
    redis_client = redis_client or make_redis(settings)
    svc = Services(settings=settings, db=db, knowledge=k, assistant=Assistant(k), limiter=RateLimiter(redis_client, settings.rate_limit_enabled),
                   auditor=Auditor(db, settings.audit_enabled))
    svc.jobs = JobService(settings, db, k, svc.auditor, redis_client)

    app = FastAPI(title="Multi-Agent Knowledge Assistant", version="3.0.0",
                  description="Multi-tenant document intelligence: upload documents or URLs, ask questions, get cited answers.")
    app.state.svc = svc
    k.obs.metrics.up.labels(app.version).set(1)
    app.state.knowledge, app.state.assistant = k, svc.assistant  # kept for tests / scripts

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                           allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID", "Retry-After"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": rid, "path": request.url.path})
            resp = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"
        k.obs.metrics.http.labels(request.method, route, str(resp.status_code)).inc()
        k.obs.metrics.http_seconds.labels(route).observe(time.perf_counter() - t0)
        resp.headers["X-Request-ID"] = rid
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        log.info("request", extra={"request_id": rid, "path": request.url.path, "status": resp.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return resp

    for r in (auth.router, feedback.router, learn.router, features.router, memory.router, reports.router, analytics.router, sources.router, jobs.router, chat.router, intel.router, evaluation.router, admin.router):
        app.include_router(r)

    @app.get("/metrics", tags=["system"], include_in_schema=False)
    def metrics(request: Request):
        """Prometheus exposition. Open when auth is disabled; otherwise needs `Authorization: Bearer <MKA_METRICS_TOKEN>` or an admin JWT."""
        import hmac

        from fastapi import HTTPException, Response

        if not settings.metrics_enabled:
            raise HTTPException(404, "Metrics are disabled")
        if settings.auth_enabled:
            tok = request.headers.get("authorization", "").partition(" ")[2]
            want = settings.secret("metrics_token")
            if not (want and tok and hmac.compare_digest(tok.encode(), want.encode())):
                p = get_principal(request, svc)  # raises 401 without a valid JWT
                if p.role != "admin":
                    raise HTTPException(403, "Metrics need an admin token or the metrics bearer token")
        return Response(k.obs.metrics.render(), media_type=k.obs.metrics.content_type)

    @app.get("/health", tags=["system"])
    def health():
        s = k.stats
        return {"status": "ok", "version": app.version, "embedder": k.embedder.name, "llm": k.llm.name, "vector_store": settings.vector_store,
                "auth_enabled": settings.auth_enabled,
                "usage": {"ingested": s.ingested, "failed": s.failed, "questions": s.questions, "embedded_chars": s.embedded_chars, "llm_calls": k.llm.calls}}

    @app.delete("/session", tags=["chat"])
    def clear_workspace(ctx: Ctx = Depends(require("delete_any"))):
        """Delete ALL sources of the current workspace (X-Session-ID) and its conversation memory."""
        st = k.store(ctx.scope)
        n = 0
        for m in st.list_sources():
            k.backend.delete(st, m["id"])
            n += 1
        st.clear()
        k.registry.delete_scope(ctx.scope.tenant, ctx.scope.workspace)
        svc.assistant.forget_workspace(ctx.scope)
        from sqlalchemy import select

        from ..db import Conversation

        with db.session() as ses:
            for cv in ses.scalars(select(Conversation).where(Conversation.tenant_id == ctx.principal.tenant_id, Conversation.workspace == ctx.scope.workspace)):
                ses.delete(cv)
        ctx.audit("clear_workspace", ctx.scope.workspace, detail={"sources_removed": n})
        return {"cleared": ctx.scope.workspace, "sources_removed": n}

    @app.get("/", include_in_schema=False)
    def ui():
        index = FRONTEND_DIST / "index.html"
        return FileResponse(index if index.exists() else STATIC / "index.html", headers={"Content-Security-Policy": CSP})

    if (FRONTEND_DIST / "assets").exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/classic", include_in_schema=False)
    def classic():
        return FileResponse(STATIC / "index.html", headers={"Content-Security-Policy": CSP})

    return app
