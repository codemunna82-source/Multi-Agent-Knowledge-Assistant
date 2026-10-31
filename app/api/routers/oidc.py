from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ...db import OidcIdentity, Tenant, User
from ...security import oidc
from ...security.auth import hash_password, issue_refresh
from ..deps import Services, get_svc, rate_limit
from .auth import COOKIE, _ip

router = APIRouter(prefix="/auth/oidc", tags=["auth"])


def _deny(svc: Services, request: Request, why: str, status: int = 403, **detail):
    svc.auditor.record("login", outcome="denied", detail={"via": "oidc", "reason": why, **detail}, ip=_ip(request), request_id=request.state.request_id)
    raise HTTPException(status, why)


@router.get("/config")
def config(svc: Services = Depends(get_svc)):
    """Public: lets the login page decide whether to show the 'Sign in with SSO' button."""
    return {"enabled": oidc.enabled(svc.settings), "login_url": "/auth/oidc/login" if oidc.enabled(svc.settings) else None}


@router.get("/login", dependencies=[Depends(rate_limit("auth"))])
def login(svc: Services = Depends(get_svc)):
    s = svc.settings
    if not oidc.enabled(s):
        raise HTTPException(404, "Single sign-on is not configured")
    tx = oidc.new_transaction()
    try:
        url = oidc.authorization_url(s, tx)
    except oidc.OidcError as e:
        raise HTTPException(502, str(e))
    resp = RedirectResponse(url, status_code=302)
    # SameSite=Lax: the IdP redirects back with a top-level GET, which Strict would not carry
    resp.set_cookie(oidc.TX_COOKIE, oidc.seal(s, tx), max_age=oidc.TX_TTL, httponly=True, samesite="lax", secure=s.env == "production", path="/auth/oidc")
    return resp


@router.get("/callback", dependencies=[Depends(rate_limit("auth"))])
def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None,
             tx_cookie: Optional[str] = Cookie(default=None, alias=oidc.TX_COOKIE), svc: Services = Depends(get_svc)):
    s = svc.settings
    if not oidc.enabled(s):
        raise HTTPException(404, "Single sign-on is not configured")
    if error:
        _deny(svc, request, "The identity provider reported an error", 400, idp_error=error[:60])
    try:
        tx = oidc.unseal(s, tx_cookie)
        if not code or not state or not secrets.compare_digest(state, tx["state"]):
            raise oidc.OidcError("State mismatch - start the login again")
        claims = oidc.validate_id_token(s, oidc.exchange_code(s, code, tx["verifier"])["id_token"], tx["nonce"])
    except oidc.OidcError as e:
        _deny(svc, request, str(e), 401)
    email = str(claims.get("email", "")).strip().lower()
    verified = claims.get("email_verified") in (True, "true")
    issuer, sub = s.oidc_issuer.rstrip("/"), str(claims["sub"])
    with svc.db.session() as db:
        link = db.scalar(select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == sub))
        user = db.get(User, link.user_id) if link else None
        if not user:
            if not (email and verified):
                _deny(svc, request, "The identity provider did not provide a verified e-mail address")
            if not oidc.domain_allowed(s, email):
                _deny(svc, request, "This e-mail domain is not allowed to sign in", email_domain=email.rsplit("@", 1)[-1])
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                if not (s.oidc_auto_provision and s.oidc_tenant_id and db.get(Tenant, s.oidc_tenant_id)):
                    _deny(svc, request, "No account exists for this user. Ask an administrator to invite you.")
                role = s.oidc_default_role if s.oidc_default_role in ("user", "manager") else "user"      # SSO can never mint admins
                user = User(tenant_id=s.oidc_tenant_id, email=email, password_hash=hash_password(secrets.token_urlsafe(32) + "Aa1!"), role=role)
                db.add(user)
                db.flush()
            db.add(OidcIdentity(user_id=user.id, issuer=issuer, subject=sub))
        if not user.is_active:
            _deny(svc, request, "This account is disabled")
        refresh = issue_refresh(db, s, user.id, ip=_ip(request))
        uid, tid = user.id, user.tenant_id
    svc.auditor.record("login", tenant_id=tid, user_id=uid, detail={"via": "oidc"}, ip=_ip(request), request_id=request.state.request_id)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, refresh, max_age=s.refresh_token_days * 86400, httponly=True, samesite="strict", secure=s.env == "production", path="/auth")
    resp.delete_cookie(oidc.TX_COOKIE, path="/auth/oidc")
    return resp
