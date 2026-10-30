from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import select

from ...db import RevokedToken, Tenant, User
from ...schemas import LoginRequest, RefreshRequest, SignupRequest, TokenResponse, UserOut
from ...security.auth import AuthError, Principal, RefreshReuse, create_token, hash_password, issue_refresh, revoke_refresh, rotate_refresh, verify_password
from ..deps import Services, get_principal, get_svc, rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "mka_refresh"


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, tenant_id=u.tenant_id, email=u.email, role=u.role, is_active=u.is_active)


def _ip(r: Request) -> str:
    return r.client.host if r.client else "unknown"


def _respond(svc: Services, response: Response, user: User, refresh: str) -> TokenResponse:
    token, ttl = create_token(svc.settings, user)
    # httpOnly: JavaScript (and therefore XSS) can never read the refresh token; SameSite=Strict + path-scoped to /auth
    response.set_cookie(COOKIE, refresh, max_age=svc.settings.refresh_token_days * 86400, httponly=True, samesite="strict", secure=svc.settings.env == "production", path="/auth")
    return TokenResponse(access_token=token, expires_in=ttl, refresh_token=refresh, user=_out(user))


@router.post("/signup", response_model=TokenResponse, status_code=201, dependencies=[Depends(rate_limit("auth"))])
def signup(body: SignupRequest, request: Request, response: Response, svc: Services = Depends(get_svc)):
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
        refresh = issue_refresh(s, svc.settings, u.id, ip=_ip(request))
        out = _respond(svc, response, u, refresh)
    svc.auditor.record("signup", tenant_id=out.user.tenant_id, user_id=out.user.id, ip=_ip(request), request_id=request.state.request_id)
    return out


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("auth"))])
def login(body: LoginRequest, request: Request, response: Response, svc: Services = Depends(get_svc)):
    email = body.email.strip().lower()
    with svc.db.session() as s:
        u = s.scalar(select(User).where(User.email == email))
        ok = verify_password(body.password, u.password_hash if u else None) and bool(u and u.is_active)
        if not ok:
            svc.auditor.record("login", tenant_id=u.tenant_id if u else None, user_id=u.id if u else None, resource=None, outcome="denied",
                               ip=_ip(request), request_id=request.state.request_id)
            raise HTTPException(401, "Invalid email or password")  # same message for unknown user / wrong password / disabled
        refresh = issue_refresh(s, svc.settings, u.id, ip=_ip(request))
        out = _respond(svc, response, u, refresh)
    svc.auditor.record("login", tenant_id=out.user.tenant_id, user_id=out.user.id, ip=_ip(request), request_id=request.state.request_id)
    return out


class NoSession(BaseModel):
    authenticated: bool = False


@router.post("/refresh", response_model=TokenResponse | NoSession, dependencies=[Depends(rate_limit("auth"))])
def refresh(request: Request, response: Response, optional: bool = False, body: Optional[RefreshRequest] = None, cookie: Optional[str] = Cookie(default=None, alias=COOKIE),
            svc: Services = Depends(get_svc)):
    """Exchange a refresh token (body or httpOnly cookie) for a new access token; the refresh token rotates on every use.
    `optional=true` (used by the browser on page load): a missing or invalid token answers 200 {"authenticated": false} instead of 401, so signed-out visits stay quiet."""
    token = (body.refresh_token if body else None) or cookie
    if not token:
        if optional:
            return NoSession()
        raise HTTPException(401, "No refresh token")
    try:
        user, new = rotate_refresh(svc.db, svc.settings, token, _ip(request))
    except RefreshReuse as e:
        svc.auditor.record("refresh_reuse_detected", tenant_id=e.tenant_id, user_id=e.user_id, outcome="denied", ip=_ip(request), request_id=request.state.request_id)
        response.delete_cookie(COOKIE, path="/auth")
        raise HTTPException(401, str(e))
    except AuthError as e:
        response.delete_cookie(COOKIE, path="/auth")
        if optional:
            return NoSession()
        raise HTTPException(401, str(e))
    out = _respond(svc, response, user, new)
    svc.auditor.record("token_refresh", tenant_id=user.tenant_id, user_id=user.id, ip=_ip(request), request_id=request.state.request_id)
    return out


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(get_principal)):
    return UserOut(id=p.user_id, tenant_id=p.tenant_id, email=p.email, role=p.role)


@router.post("/logout")
def logout(request: Request, response: Response, body: Optional[RefreshRequest] = None, cookie: Optional[str] = Cookie(default=None, alias=COOKIE),
           p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    """Revokes the access token and the whole refresh-token family of this login."""
    jti = getattr(request.state, "jti", None)
    if jti:
        with svc.db.session() as s:
            if not s.get(RevokedToken, jti):
                s.add(RevokedToken(jti=jti, expires_at=datetime.fromtimestamp(request.state.token_exp, UTC)))
    token = (body.refresh_token if body else None) or cookie
    if token:
        revoke_refresh(svc.db, token)
    response.delete_cookie(COOKIE, path="/auth")
    if jti or token:
        svc.auditor.record("logout", tenant_id=p.tenant_id, user_id=p.user_id, ip=_ip(request), request_id=request.state.request_id)
    return {"logged_out": True}
