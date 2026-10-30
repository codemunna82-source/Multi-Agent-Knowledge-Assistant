"""Request context: authentication, workspace scoping, permission checks, rate limits, auditing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Callable

from fastapi import Depends, Header, HTTPException, Query, Request, Response

from ..config import Settings
from ..db import Database, RevokedToken, User
from ..security.audit import Auditor
from ..security.auth import ANONYMOUS, AuthError, Principal, decode_token
from ..security.ratelimit import RateLimiter
from ..storage import SESSION_RE, Scope


@dataclass
class Services:
    settings: Settings
    db: Database
    knowledge: object
    assistant: object
    limiter: RateLimiter
    auditor: Auditor
    jobs: object = None


@dataclass
class Ctx:
    request: Request
    svc: Services
    principal: Principal
    scope: Scope

    @property
    def ip(self) -> str:
        return self.request.client.host if self.request.client else "unknown"

    def audit(self, action: str, resource: str | None = None, outcome: str = "success", detail: dict | None = None) -> None:
        self.svc.auditor.record(action, tenant_id=self.principal.tenant_id, user_id=self.principal.user_id, resource=resource, outcome=outcome,
                                ip=self.ip, request_id=getattr(self.request.state, "request_id", None), detail=detail)


def get_svc(request: Request) -> Services:
    return request.app.state.svc


def get_principal(request: Request, svc: Services = Depends(get_svc)) -> Principal:
    if not svc.settings.auth_enabled:
        return ANONYMOUS
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(svc.settings, token)
    except AuthError as e:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})
    with svc.db.session() as s:
        if s.get(RevokedToken, claims["jti"]):
            raise HTTPException(401, "Token revoked", headers={"WWW-Authenticate": "Bearer"})
        user = s.get(User, claims["sub"])
        if not user or not user.is_active or user.tenant_id != claims["tid"]:
            raise HTTPException(401, "Account disabled or removed", headers={"WWW-Authenticate": "Bearer"})
        request.state.jti, request.state.token_exp = claims["jti"], claims["exp"]
        return Principal(user.id, user.tenant_id, user.role, user.email)  # role is read fresh: changes apply immediately


def rate_limit(kind: str) -> Callable:
    def dep(request: Request, svc: Services = Depends(get_svc)):
        spec = getattr(svc.settings, f"rate_limit_{kind}")
        who = getattr(request.state, "principal_id", None) or (request.client.host if request.client else "unknown")
        ok, retry = svc.limiter.hit(f"{kind}:{who}", spec)
        if not ok:
            svc.auditor.record("rate_limited", resource=kind, outcome="denied", ip=request.client.host if request.client else None,
                               request_id=getattr(request.state, "request_id", None))
            raise HTTPException(429, f"Rate limit exceeded ({spec}). Retry in {retry}s.", headers={"Retry-After": str(retry)})
    return dep


def require(permission: str, limit: str | None = None) -> Callable:
    def dep(request: Request, svc: Services = Depends(get_svc), principal: Principal = Depends(get_principal),
            x_session_id: str = Header(default="default")) -> Ctx:
        request.state.principal_id = principal.user_id
        if not principal.can(permission):
            svc.auditor.record("permission_denied", tenant_id=principal.tenant_id, user_id=principal.user_id, resource=permission, outcome="denied",
                               ip=request.client.host if request.client else None, request_id=getattr(request.state, "request_id", None))
            raise HTTPException(403, f"Your role ({principal.role}) may not perform '{permission}'")
        if limit:
            rate_limit(limit)(request, svc)
        if not SESSION_RE.match(x_session_id):
            raise HTTPException(400, "Invalid X-Session-ID (1-64 letters, digits, '-' or '_')")
        return Ctx(request, svc, principal, Scope(principal.tenant_id, x_session_id))
    return dep


def utcnow() -> datetime:
    return datetime.now(UTC)


def page_params(limit: int = Query(50, ge=1, le=200, description="page size"), offset: int = Query(0, ge=0)) -> tuple[int, int]:
    return limit, offset


def paginate(items: list, response: Response, page: tuple[int, int]) -> list:
    """Slice an in-memory list; the full size is reported in the X-Total-Count header."""
    limit, offset = page
    response.headers["X-Total-Count"] = str(len(items))
    return items[offset:offset + limit]
