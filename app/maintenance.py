"""Scheduled maintenance: retention sweeps and housekeeping. Runs from `python -m app.scheduler` (periodic, single leader) or on demand
from POST /admin/maintenance/run. Every task supports `dry_run` and reports exactly what it removed (or would remove).

Retention is per tenant (Settings -> retention_days_*; empty = keep forever):
  documents      a logical document whose NEWEST version is older than N days is deleted with all versions, vectors and files
  conversations  conversations with no activity for N days (messages are removed with them)
  audit          audit events older than N days (the sweep itself is audited first)
  reports        generated report rows and files older than N days
Global housekeeping: finished jobs, expired refresh tokens, expired revoked-token ids."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import delete, func, select

from .db import AuditEvent, Conversation, Document, Job, RefreshToken, Report, RevokedToken, TenantSettings
from .storage import Scope

log = logging.getLogger("mka.maintenance")
TASKS = ("retention_documents", "retention_conversations", "retention_audit", "retention_reports", "cleanup_jobs", "cleanup_tokens", "run_report_schedules", "sync_connectors")


def _cutoff(days: int, now: datetime) -> datetime:
    return now - timedelta(days=days)


def _tenants(db, field: str, only: Optional[str] = None) -> list[tuple[str, int]]:
    with db.session() as s:
        q = select(TenantSettings) if only is None else select(TenantSettings).where(TenantSettings.tenant_id == only)
        return [(r.tenant_id, getattr(r, field)) for r in s.scalars(q) if getattr(r, field)]


def retention_documents(k, now, dry_run, only=None, auditor=None, **_) -> dict:
    removed, names = 0, []
    for tenant, days in _tenants(k.db, "retention_days_documents", only):
        cut = _cutoff(days, now)
        with k.db.session() as s:
            newest = s.execute(select(Document.workspace, Document.doc_key, func.max(Document.created_at)).where(Document.tenant_id == tenant).group_by(Document.workspace, Document.doc_key)).all()
            expired = [(ws, key) for ws, key, ts in newest if (ts if ts.tzinfo else ts.replace(tzinfo=UTC)) < cut]
            current = {(d.workspace, d.doc_key): d.id for d in s.scalars(select(Document).where(Document.tenant_id == tenant, Document.is_current.is_(True)))}
        for ws, key in expired:
            sid = current.get((ws, key))
            if sid is None:
                with k.db.session() as s:  # no current version (should not happen): fall back to the newest row
                    sid = s.scalar(select(Document.id).where(Document.tenant_id == tenant, Document.workspace == ws, Document.doc_key == key).order_by(Document.version.desc()).limit(1))
            names.append(f"{tenant}/{ws}/{key}")
            if not dry_run and sid and k.delete(Scope(tenant, ws), sid, None, all_versions=True):
                removed += 1
        if expired and not dry_run and auditor:
            auditor.record("retention_sweep", tenant_id=tenant, resource="documents", detail={"days": days, "documents": len(expired)})
    return {"removed": len(names) if dry_run else removed, "items": names[:50]}


def retention_conversations(k, now, dry_run, only=None, assistant=None, auditor=None, **_) -> dict:
    n = 0
    for tenant, days in _tenants(k.db, "retention_days_conversations", only):
        cut = _cutoff(days, now)
        with k.db.session() as s:
            old = s.scalars(select(Conversation).where(Conversation.tenant_id == tenant, Conversation.updated_at < cut)).all()
            ids = [(c.id, c.workspace, c.user_id) for c in old]
            if not dry_run:
                for c in old:
                    s.delete(c)
        n += len(ids)
        if not dry_run:
            if assistant is not None:
                for cid, ws, uid in ids:
                    assistant.forget(Scope(tenant, ws), cid, uid)
            if ids and auditor:
                auditor.record("retention_sweep", tenant_id=tenant, resource="conversations", detail={"days": days, "conversations": len(ids)})
    return {"removed": n}


def retention_audit(k, now, dry_run, only=None, auditor=None, **_) -> dict:
    n = 0
    for tenant, days in _tenants(k.db, "retention_days_audit", only):
        cut = _cutoff(days, now)
        with k.db.session() as s:
            count = s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant, AuditEvent.ts < cut)) or 0
            if count and not dry_run:
                s.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant, AuditEvent.ts < cut))
        n += count
        if count and not dry_run and auditor:
            auditor.record("retention_sweep", tenant_id=tenant, resource="audit", detail={"days": days, "events": count})  # written AFTER the delete, so it survives
    return {"removed": n}


def retention_reports(k, now, dry_run, only=None, auditor=None, **_) -> dict:
    n = 0
    for tenant, days in _tenants(k.db, "retention_days_reports", only):
        cut = _cutoff(days, now)
        with k.db.session() as s:
            old = s.scalars(select(Report).where(Report.tenant_id == tenant, Report.created_at < cut)).all()
            paths = [r.path for r in old if r.path]
            if not dry_run:
                for r in old:
                    s.delete(r)
        if not dry_run:
            for p in paths:
                Path(p).unlink(missing_ok=True)
            if old and auditor:
                auditor.record("retention_sweep", tenant_id=tenant, resource="reports", detail={"days": days, "reports": len(old)})
        n += len(old)
    return {"removed": n}


def cleanup_jobs(k, now, dry_run, only=None, **_) -> dict:
    cut = _cutoff(k.settings.finished_jobs_retention_days, now)
    with k.db.session() as s:
        cond = (Job.status.in_(("ready", "failed")), Job.updated_at < cut) + ((Job.tenant_id == only,) if only else ())
        n = s.scalar(select(func.count()).select_from(Job).where(*cond)) or 0
        if n and not dry_run:
            s.execute(delete(Job).where(*cond))
    return {"removed": n}


def run_report_schedules(k, now, dry_run, only=None, assistant=None, auditor=None, **_) -> dict:
    from . import automation
    from .db import ReportSchedule

    with k.db.session() as s:
        q = select(ReportSchedule).where(ReportSchedule.enabled.is_(True))
        rows = [r for r in s.scalars(q if only is None else q.where(ReportSchedule.tenant_id == only)) if automation.due(r.last_run_at, r.every_hours, now)]
        s.expunge_all()
    if dry_run:
        return {"removed": 0, "due": [r.name for r in rows]}
    if rows and assistant is None:
        from .agents import Assistant

        assistant = Assistant(k)
    out = []
    for r in rows:
        status = automation.run_schedule(k, assistant, r)
        with k.db.session() as s:
            row = s.get(ReportSchedule, r.id)
            row.last_run_at, row.last_status = now, status[:300]
        out.append({"schedule": r.name, "status": status})
    return {"removed": 0, "ran": out}


def sync_connectors(k, now, dry_run, only=None, assistant=None, auditor=None, **_) -> dict:
    from . import automation
    from .db import Connector

    with k.db.session() as s:
        q = select(Connector).where(Connector.enabled.is_(True))
        rows = [c for c in s.scalars(q if only is None else q.where(Connector.tenant_id == only)) if automation.due(c.last_run_at, c.every_hours, now)]
        s.expunge_all()
    if dry_run:
        return {"removed": 0, "due": [c.name for c in rows]}
    out = []
    for c in rows:
        res = automation.sync(k, c)
        with k.db.session() as s:
            row = s.get(Connector, c.id)
            row.last_run_at, row.last_result = now, res
        out.append({"connector": c.name, **{a: b for a, b in res.items() if a != "errors"}, "errors": len(res["errors"])})
    return {"removed": 0, "ran": out}


def cleanup_tokens(k, now, dry_run, only=None, **_) -> dict:
    if only:
        return {"removed": 0, "skipped": "global task: run by the scheduler"}
    with k.db.session() as s:
        a = s.scalar(select(func.count()).select_from(RevokedToken).where(RevokedToken.expires_at < now)) or 0
        b = s.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.expires_at < _cutoff(7, now))) or 0
        if not dry_run:
            s.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
            s.execute(delete(RefreshToken).where(RefreshToken.expires_at < _cutoff(7, now)))
    return {"removed": a + b, "revoked_access_tokens": a, "refresh_tokens": b}


_FN: dict[str, Callable] = {t: globals()[t] for t in TASKS}


def run(k, tasks: Optional[list[str]] = None, dry_run: bool = False, now: Optional[datetime] = None, assistant=None, auditor=None, tenant: Optional[str] = None) -> dict:
    """-> {task: {"removed": n, ...} | {"error": "..."}}. One failing task never stops the others. `tenant` restricts every task to one organisation."""
    now = now or datetime.now(UTC)
    wanted = list(tasks) if tasks else list(TASKS)
    unknown = [t for t in wanted if t not in _FN]
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    out = {}
    for t in wanted:
        try:
            out[t] = _FN[t](k, now, dry_run, only=tenant, assistant=assistant, auditor=auditor)
            k.obs.metrics.maintenance.labels(t, "dry_run" if dry_run else "ok").inc()
        except Exception as e:
            log.exception("maintenance task %s failed", t)
            out[t] = {"error": type(e).__name__}
            k.obs.metrics.maintenance.labels(t, "error").inc()
    return out
