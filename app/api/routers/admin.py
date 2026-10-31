from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select

from ...db import AuditEvent, Conversation, EvalRun, Job, MemoryFact, RefreshToken, Report, TenantSettings, User
from ... import maintenance
from ...schemas import AuditOut, PurgeRequest, UserCreate, UserOut, UserUpdate
from ...security.auth import hash_password
from ..deps import Ctx, page_params, require

router = APIRouter(prefix="/admin", tags=["admin"])

PURGE_PHRASE = "DELETE-ALL-TENANT-DATA"


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, tenant_id=u.tenant_id, email=u.email, role=u.role, is_active=u.is_active)


def _active_admins(s, tenant_id: str) -> int:
    return s.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant_id, User.role == "admin", User.is_active.is_(True)))


@router.get("/users", response_model=list[UserOut])
def users(response: Response, page: tuple[int, int] = Depends(page_params), ctx: Ctx = Depends(require("manage_users"))):
    with ctx.svc.db.session() as s:
        q = select(User).where(User.tenant_id == ctx.principal.tenant_id)
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(q.subquery())))
        return [_out(u) for u in s.scalars(q.order_by(User.created_at).limit(page[0]).offset(page[1]))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, ctx: Ctx = Depends(require("manage_users"))):
    email = body.email.strip().lower()
    try:
        pw = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with ctx.svc.db.session() as s:
        if s.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "An account with this email already exists")
        u = User(tenant_id=ctx.principal.tenant_id, email=email, password_hash=pw, role=body.role)
        s.add(u)
        s.flush()
        out = _out(u)
    ctx.audit("create_user", out.id, detail={"role": body.role})
    return out


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, ctx: Ctx = Depends(require("manage_users"))):
    with ctx.svc.db.session() as s:
        u = s.get(User, user_id)
        if not u or u.tenant_id != ctx.principal.tenant_id:
            raise HTTPException(404, "User not found")
        losing_admin = u.role == "admin" and ((body.role and body.role != "admin") or body.is_active is False)
        if losing_admin and _active_admins(s, u.tenant_id) <= 1:
            raise HTTPException(409, "Cannot remove the last active admin")
        if body.role is not None:
            u.role = body.role
        if body.is_active is not None:
            u.is_active = body.is_active
        if body.password:
            u.password_hash = hash_password(body.password)
        out = _out(u)
    ctx.audit("update_user", user_id, detail=body.model_dump(exclude={"password"}, exclude_none=True))
    return out


@router.delete("/users/{user_id}")
def delete_user(user_id: str, ctx: Ctx = Depends(require("manage_users"))):
    with ctx.svc.db.session() as s:
        u = s.get(User, user_id)
        if not u or u.tenant_id != ctx.principal.tenant_id:
            raise HTTPException(404, "User not found")
        if u.role == "admin" and _active_admins(s, u.tenant_id) <= 1:
            raise HTTPException(409, "Cannot remove the last active admin")
        for c in s.scalars(select(Conversation).where(Conversation.user_id == user_id)):
            s.delete(c)
        s.execute(delete(MemoryFact).where(MemoryFact.user_id == user_id))
        s.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        reports = s.scalars(select(Report).where(Report.user_id == user_id)).all()
        paths = [r.path for r in reports if r.path]
        for r in reports:
            s.delete(r)
        s.delete(u)
    for p in paths:
        Path(p).unlink(missing_ok=True)
    ctx.audit("delete_user", user_id, detail={"reports_deleted": len(paths)})
    return {"deleted": user_id}


@router.get("/audit/export", summary="Audit trail for a SIEM: ndjson, csv or CEF (one event per line); never contains question or document text")
def audit_export(format: str = Query("ndjson", pattern="^(ndjson|csv|cef)$"), since: Optional[str] = Query(None, description="ISO timestamp"), limit: int = Query(10000, ge=1, le=100000), ctx: Ctx = Depends(require("audit"))):
    import csv
    import io
    import json
    from datetime import datetime

    with ctx.svc.db.session() as s:
        q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.principal.tenant_id)
        if since:
            try:
                q = q.where(AuditEvent.ts >= datetime.fromisoformat(since))
            except ValueError:
                raise HTTPException(422, "since must be an ISO timestamp")
        rows = s.scalars(q.order_by(AuditEvent.id).limit(limit)).all()
        ev = [{"id": r.id, "ts": r.ts.isoformat(), "tenant_id": r.tenant_id, "user_id": r.user_id, "action": r.action, "resource": r.resource, "outcome": r.outcome, "ip": r.ip, "request_id": r.request_id,
               "detail": r.detail} for r in rows]
    if format == "ndjson":
        return Response("\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + ("\n" if ev else ""), media_type="application/x-ndjson")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "ts", "tenant_id", "user_id", "action", "resource", "outcome", "ip", "request_id", "detail"])
        for e in ev:  # cells starting with = + - @ are neutralised (spreadsheet formula injection)
            w.writerow([("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for v in (e["id"], e["ts"], e["tenant_id"], e["user_id"], e["action"], e["resource"], e["outcome"], e["ip"], e["request_id"], json.dumps(e["detail"]) if e["detail"] else "")])
        return Response(buf.getvalue(), media_type="text/csv")
    esc = lambda v: str(v if v is not None else "").replace("\\", "\\\\").replace("=", "\\=").replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = [f"CEF:0|MKA|KnowledgeAssistant|3.1|{esc(e['action'])}|{esc(e['action'])}|{1 if e['outcome'] == 'success' else 5}|rt={esc(e['ts'])} suser={esc(e['user_id'])} src={esc(e['ip'])} "
             f"outcome={esc(e['outcome'])} cs1Label=resource cs1={esc(e['resource'])} cs2Label=requestId cs2={esc(e['request_id'])}" for e in ev]
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="text/plain")


@router.get("/audit", response_model=list[AuditOut])
def audit(response: Response, ctx: Ctx = Depends(require("audit")), action: str | None = None, outcome: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    with ctx.svc.db.session() as s:
        base = select(AuditEvent).where(AuditEvent.tenant_id == ctx.principal.tenant_id)
        if action:
            base = base.where(AuditEvent.action == action)
        if outcome:
            base = base.where(AuditEvent.outcome == outcome)
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(base.subquery())))
        q = base.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
        return [AuditOut(id=a.id, ts=a.ts.isoformat(), user_id=a.user_id, action=a.action, resource=a.resource, outcome=a.outcome, ip=a.ip,
                         request_id=a.request_id, detail=a.detail) for a in s.scalars(q)]


@router.get("/settings")
def settings(ctx: Ctx = Depends(require("settings"))):
    """Effective configuration; secrets are masked and never returned."""
    return ctx.svc.settings.public_dict()


@router.delete("/data")
def purge_tenant(body: PurgeRequest, ctx: Ctx = Depends(require("purge"))):
    """Irreversibly erase every document, vector, conversation, job and evaluation of the caller's tenant (users are kept)."""
    if body.confirm != PURGE_PHRASE:
        raise HTTPException(422, f"Set confirm to '{PURGE_PHRASE}'")
    k, tid = ctx.svc.knowledge, ctx.principal.tenant_id
    root = Path(k.settings.data_dir) / "tenants" / tid / "workspaces"
    removed = 0
    if root.exists():
        from ...storage import Scope

        for ws in sorted(p.name for p in root.iterdir() if p.is_dir()):
            scope = Scope(tid, ws)
            st = k.store(scope)
            for m in st.list_sources():
                k.backend.delete(st, m["id"])
                removed += 1
            st.clear()
            ctx.svc.assistant.forget_workspace(scope)
        shutil.rmtree(Path(k.settings.data_dir) / "tenants" / tid, ignore_errors=True)
    k.registry.delete_scope(tid)
    with ctx.svc.db.session() as s:
        for c in s.scalars(select(Conversation).where(Conversation.tenant_id == tid)):
            s.delete(c)
        s.execute(delete(Job).where(Job.tenant_id == tid))
        s.execute(delete(EvalRun).where(EvalRun.tenant_id == tid))
        s.execute(delete(Report).where(Report.tenant_id == tid))
        s.execute(delete(MemoryFact).where(MemoryFact.tenant_id == tid))
    ctx.audit("purge_tenant_data", tid, detail={"sources_removed": removed})
    return {"purged": True, "sources_removed": removed}


class TenantSettingsBody(BaseModel):
    retention_days_documents: Optional[int] = Field(default=None, ge=1, le=36500, description="delete documents older than N days (null = keep)")
    retention_days_conversations: Optional[int] = Field(default=None, ge=1, le=36500)
    retention_days_audit: Optional[int] = Field(default=None, ge=30, le=36500, description="audit trail is never kept for less than 30 days")
    retention_days_reports: Optional[int] = Field(default=None, ge=1, le=36500)
    web_allowed: bool = True
    web_allowed_domains: list[str] = Field(default_factory=list, max_length=200, description="empty = any public domain; otherwise only these domains (and sub-domains)")
    redact_stored_messages: bool = False


def get_tenant_settings(db, tenant_id: str) -> TenantSettings:
    with db.session() as s:
        row = s.get(TenantSettings, tenant_id)
        if row is None:
            row = TenantSettings(tenant_id=tenant_id, web_allowed_domains=[])
            s.add(row)
            s.flush()
        s.expunge(row)
        return row


@router.get("/tenant-settings", response_model=TenantSettingsBody)
def tenant_settings(ctx: Ctx = Depends(require("settings"))):
    r = get_tenant_settings(ctx.svc.db, ctx.principal.tenant_id)
    return TenantSettingsBody(**{f: getattr(r, f) for f in TenantSettingsBody.model_fields})


@router.put("/tenant-settings", response_model=TenantSettingsBody)
def put_tenant_settings(body: TenantSettingsBody, ctx: Ctx = Depends(require("settings"))):
    """Retention periods, approved web domains and message redaction for the whole organisation."""
    import re

    domains = [d.strip().lower().lstrip(".") for d in body.web_allowed_domains if d.strip()]
    if any(not re.fullmatch(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?", d) or "." not in d for d in domains):
        raise HTTPException(422, "web_allowed_domains must be plain domain names such as example.com")
    with ctx.svc.db.session() as s:
        row = s.get(TenantSettings, ctx.principal.tenant_id) or TenantSettings(tenant_id=ctx.principal.tenant_id)
        for f in TenantSettingsBody.model_fields:
            setattr(row, f, domains if f == "web_allowed_domains" else getattr(body, f))
        s.merge(row)
    ctx.audit("update_tenant_settings", ctx.principal.tenant_id, detail=body.model_dump())
    return body.model_copy(update={"web_allowed_domains": domains})


class MaintenanceBody(BaseModel):
    tasks: Optional[list[str]] = Field(default=None, description=f"subset of: {', '.join(maintenance.TASKS)} (default: all)")
    dry_run: bool = True


@router.post("/maintenance/run", summary="Run retention sweeps and housekeeping now (dry run by default). Retention only touches YOUR tenant's data.")
def run_maintenance(body: MaintenanceBody, ctx: Ctx = Depends(require("purge"))):
    """Same tasks as the scheduler, restricted to your organisation. Retention periods come from /admin/tenant-settings."""
    try:
        res = maintenance.run(ctx.svc.knowledge, body.tasks, body.dry_run, assistant=ctx.svc.assistant, auditor=ctx.svc.auditor, tenant=ctx.principal.tenant_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    ctx.audit("maintenance_run", None, detail={"tasks": body.tasks or "all", "dry_run": body.dry_run})
    return {"dry_run": body.dry_run, "results": res}
