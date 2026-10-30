from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select

from ...db import AuditEvent, Conversation, EvalRun, Job, User
from ...schemas import AuditOut, PurgeRequest, UserCreate, UserOut, UserUpdate
from ...security.auth import hash_password
from ..deps import Ctx, require

router = APIRouter(prefix="/admin", tags=["admin"])

PURGE_PHRASE = "DELETE-ALL-TENANT-DATA"


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, tenant_id=u.tenant_id, email=u.email, role=u.role, is_active=u.is_active)


def _active_admins(s, tenant_id: str) -> int:
    return s.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant_id, User.role == "admin", User.is_active.is_(True)))


@router.get("/users", response_model=list[UserOut])
def users(ctx: Ctx = Depends(require("manage_users"))):
    with ctx.svc.db.session() as s:
        return [_out(u) for u in s.scalars(select(User).where(User.tenant_id == ctx.principal.tenant_id).order_by(User.created_at))]


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
        s.delete(u)
    ctx.audit("delete_user", user_id)
    return {"deleted": user_id}


@router.get("/audit", response_model=list[AuditOut])
def audit(ctx: Ctx = Depends(require("audit")), action: str | None = None, limit: int = Query(100, le=1000)):
    with ctx.svc.db.session() as s:
        q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.principal.tenant_id).order_by(AuditEvent.id.desc()).limit(limit)
        if action:
            q = q.where(AuditEvent.action == action)
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
    with ctx.svc.db.session() as s:
        for c in s.scalars(select(Conversation).where(Conversation.tenant_id == tid)):
            s.delete(c)
        s.execute(delete(Job).where(Job.tenant_id == tid))
        s.execute(delete(EvalRun).where(EvalRun.tenant_id == tid))
    ctx.audit("purge_tenant_data", tid, detail={"sources_removed": removed})
    return {"purged": True, "sources_removed": removed}
