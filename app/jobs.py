"""Background ingestion: durable job rows (PostgreSQL) + a queue (in-process thread pool, or Redis for separate workers).

A job only runs if it can atomically move queued -> running, so duplicate deliveries (Redis redelivery, double submit)
are harmless. Transient failures (embedding API errors) are retried a bounded number of times with backoff;
invalid input is never retried."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update

from .config import Settings
from .db import Database, Job, now
from .security.audit import Auditor
from .storage import Scope

log = logging.getLogger("mka.jobs")
QUEUE = "mka:jobs"
PROCESSING = "mka:jobs:processing"


class JobService:
    def __init__(self, settings: Settings, db: Database, knowledge, auditor: Auditor, redis_client=None):
        self.s, self.db, self.k, self.auditor, self.redis = settings, db, knowledge, auditor, redis_client
        self.backend = settings.job_backend
        if self.backend == "redis" and redis_client is None:
            raise RuntimeError("MKA_JOB_BACKEND=redis requires MKA_REDIS_URL")
        self._pool: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ submit
    def upload_dir(self, tenant: str) -> Path:
        d = Path(self.s.data_dir) / "_uploads" / tenant
        d.mkdir(parents=True, exist_ok=True)
        return d

    def submit(self, *, tenant: str, user: str, workspace: str, kind: str, name: str, payload: dict) -> str:
        with self.db.session() as s:
            j = Job(tenant_id=tenant, user_id=user, workspace=workspace, kind=kind, name=name[:2048], payload=payload)
            s.add(j)
            s.flush()
            jid = j.id
        self._enqueue(jid)
        return jid

    def _enqueue(self, job_id: str) -> None:
        if self.backend == "redis":
            self.redis.lpush(QUEUE, job_id)
            return
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self.s.job_workers, thread_name_prefix="ingest")
        self._pool.submit(self.run, job_id)

    def shutdown(self) -> None:
        if self._pool:
            self._pool.shutdown(wait=True)

    # ------------------------------------------------------------------ execute (API process or worker process)
    def _set(self, job_id: str, **kw) -> None:
        with self.db.session() as s:
            s.execute(update(Job).where(Job.id == job_id).values(updated_at=now(), **kw))

    def run(self, job_id: str) -> None:
        with self.db.session() as s:  # atomic claim
            claimed = s.execute(update(Job).where(Job.id == job_id, Job.status == "queued").values(status="running", stage="starting", progress=1, updated_at=now())).rowcount
            job = s.get(Job, job_id)
            if not claimed or job is None:
                return
            snap = dict(tenant=job.tenant_id, user=job.user_id, ws=job.workspace, kind=job.kind, name=job.name, payload=job.payload or {})
        scope = Scope(snap["tenant"], snap["ws"])
        path = Path(snap["payload"].get("path", "")) if snap["payload"].get("path") else None
        result: dict = {"status": "failed", "error": "not run", "retryable": False}
        try:
            for attempt in range(1, self.s.job_max_attempts + 1):
                self._set(job_id, attempts=attempt, stage="starting")
                cb = lambda stage, pct: self._set(job_id, stage=stage, progress=int(pct))  # noqa: E731
                if snap["kind"] == "file":
                    result = self.k.ingest_file(scope, path, snap["name"], owner_id=snap["user"], visibility=snap["payload"].get("visibility", "tenant"), progress=cb)
                elif snap["kind"] == "url":
                    result = self.k.ingest_url(scope, snap["payload"]["url"], owner_id=snap["user"], visibility=snap["payload"].get("visibility", "tenant"), progress=cb)
                else:
                    result = self.k.reindex(scope, snap["payload"]["source_id"], None, progress=cb)
                if result["status"] == "ready" or not result.get("retryable") or attempt == self.s.job_max_attempts:
                    break
                log.warning("job %s attempt %d failed (%s); retrying", job_id, attempt, result["error"])
                time.sleep(self.s.job_retry_backoff * attempt)
        except Exception as e:  # defensive: a worker must never die on one job
            log.exception("job %s crashed", job_id)
            result = {"status": "failed", "error": f"Unexpected worker error: {type(e).__name__}", "source": None}
        finally:
            if path and snap["kind"] == "file":
                shutil.rmtree(path.parent, ignore_errors=True)
        ok = result["status"] == "ready"
        self._set(job_id, status="ready" if ok else "failed", stage="done" if ok else "failed", progress=100 if ok else 0,
                  error=None if ok else result["error"], source_id=(result["source"] or {}).get("id") if ok else None)
        self.auditor.record("ingest_job", tenant_id=snap["tenant"], user_id=snap["user"], resource=snap["name"], outcome="success" if ok else "failed",
                            detail={"job_id": job_id, "source_id": (result.get("source") or {}).get("id"), "workspace": snap["ws"]})

    # ------------------------------------------------------------------ worker loop (python -m app.worker)
    def requeue_stale(self) -> int:
        cutoff = now() - timedelta(minutes=self.s.job_stale_minutes)
        with self.db.session() as s:
            ids = [j.id for j in s.scalars(select(Job).where(Job.status == "running", Job.updated_at < cutoff))]
            for i in ids:
                s.execute(update(Job).where(Job.id == i).values(status="queued", stage="requeued", updated_at=now()))
        for i in ids:
            self._enqueue(i)
        return len(ids)

    def work_forever(self, stop: threading.Event, poll: int = 2) -> None:
        assert self.backend == "redis"
        for raw in self.redis.lrange(PROCESSING, 0, -1):  # crash recovery: re-deliver what a dead worker held
            self.redis.lmove(PROCESSING, QUEUE, "RIGHT", "LEFT")
        self.requeue_stale()
        log.info("worker started")
        while not stop.is_set():
            raw = self.redis.blmove(QUEUE, PROCESSING, poll, "RIGHT", "LEFT")
            if raw is None:
                continue
            job_id = raw.decode() if isinstance(raw, bytes) else raw
            try:
                self.run(job_id)
            finally:
                self.redis.lrem(PROCESSING, 1, raw)

    # ------------------------------------------------------------------ read
    def get(self, job_id: str, tenant: str, user: str | None) -> Optional[Job]:
        with self.db.session() as s:
            j = s.get(Job, job_id)
            if j and j.tenant_id == tenant and (user is None or j.user_id == user):
                return j
        return None

    def list(self, tenant: str, user: str | None, workspace: str | None, limit: int = 50) -> list[Job]:
        with self.db.session() as s:
            q = select(Job).where(Job.tenant_id == tenant).order_by(Job.created_at.desc()).limit(limit)
            if user:
                q = q.where(Job.user_id == user)
            if workspace:
                q = q.where(Job.workspace == workspace)
            return list(s.scalars(q))
