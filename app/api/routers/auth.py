from __future__ import annotations

from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ...db import RevokedToken, Tenant, User
from ...schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from ...security.auth import Principal, create_token, hash_password, verify_password
from ..deps import Services, get_principal, get_svc, rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, tenant_id=u.tenant_id, email=u.email, role=u.role, is_active=u.is_active)


def _ip(r: Request) -> str:
    return r.client.host if r.client else "unknown"


@router.post("/signup", response_model=TokenResponse, status_code=201, dependencies=[Depends(rate_limit("auth"))])
def signup(body: SignupRequest, request: Request, svc: Services = Depends(get_svc)):
    """Create a new tenant with its first admin. Disabled in production (use `python -m app.cli create-tenant`)."""
    if not svc.settings.allow_signup:
        raise HTTPException(403, "Self-service signup is disabled")
    email = body.email.strip().lower()
    try:
        pw_hash = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with svc.db.session() as s:
        if s.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "An account with this email already exists")
        t = Tenant(name=body.tenant_name.strip())
        s.add(t)
        s.flush()
        u = User(tenant_id=t.id, email=email, password_hash=pw_hash, role="admin")
        s.add(u)
        s.flush()
        token, ttl = create_token(svc.settings, u)
        out = _out(u)
    svc.auditor.record("signup", tenant_id=out.tenant_id, user_id=out.id, ip=_ip(request), request_id=request.state.request_id)
    return TokenResponse(access_token=token, expires_in=ttl, user=out)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("auth"))])
def login(body: LoginRequest, request: Request, svc: Services = Depends(get_svc)):
    email = body.email.strip().lower()
    with svc.db.session() as s:
        u = s.scalar(select(User).where(User.email == email))
        ok = verify_password(body.password, u.password_hash if u else None) and bool(u and u.is_active)
        if not ok:
            svc.auditor.record("login", tenant_id=u.tenant_id if u else None, user_id=u.id if u else None, resource=None, outcome="denied",
                               ip=_ip(request), request_id=request.state.request_id)
            raise HTTPException(401, "Invalid email or password")  # same message for unknown user / wrong password / disabled
        token, ttl = create_token(svc.settings, u)
        out = _out(u)
    svc.auditor.record("login", tenant_id=out.tenant_id, user_id=out.id, ip=_ip(request), request_id=request.state.request_id)
    return TokenResponse(access_token=token, expires_in=ttl, user=out)


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(get_principal)):
    return UserOut(id=p.user_id, tenant_id=p.tenant_id, email=p.email, role=p.role)


@router.post("/logout")
def logout(request: Request, p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    jti = getattr(request.state, "jti", None)
    if jti:
        with svc.db.session() as s:
            if not s.get(RevokedToken, jti):
                s.add(RevokedToken(jti=jti, expires_at=datetime.fromtimestamp(request.state.token_exp, UTC)))
        svc.auditor.record("logout", tenant_id=p.tenant_id, user_id=p.user_id, ip=_ip(request), request_id=request.state.request_id)
    return {"logged_out": True}
