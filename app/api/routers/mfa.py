from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...db import User, UserMfa
from ...security import totp
from ...security.auth import Principal, verify_password
from ..deps import Services, get_principal, get_svc, rate_limit

router = APIRouter(prefix="/auth/mfa", tags=["auth"])


class Code(BaseModel):
    code: str = Field(max_length=32)


class Disable(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(max_length=32)


def check_second_factor(row: UserMfa, code: Optional[str]) -> bool:
    """Accept a TOTP code once (replay-protected) or an unused recovery code. Mutates `row`; the caller commits."""
    if not code:
        return False
    counter = totp.verify(row.secret, code, row.last_counter)
    if counter is not None:
        row.last_counter = counter
        return True
    left = totp.use_recovery(list(row.recovery_hashes or []), code)
    if left is not None:
        row.recovery_hashes = left
        return True
    return False


@router.get("")
def status(p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    with svc.db.session() as s:
        row = s.get(UserMfa, p.user_id)
        return {"enabled": bool(row and row.enabled), "recovery_codes_left": len(row.recovery_hashes or []) if row and row.enabled else 0}


@router.post("/setup", dependencies=[Depends(rate_limit("auth"))])
def setup(request: Request, p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    """Step 1: create a (not yet active) secret. Scan the otpauth URI with an authenticator app, then confirm with /auth/mfa/enable."""
    with svc.db.session() as s:
        row = s.get(UserMfa, p.user_id)
        if row and row.enabled:
            raise HTTPException(409, "MFA is already enabled; disable it first to enrol a new device")
        secret = totp.new_secret()
        if row:
            row.secret, row.last_counter = secret, 0
        else:
            s.add(UserMfa(user_id=p.user_id, secret=secret, enabled=False, recovery_hashes=[]))
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, p.email)}


@router.post("/enable", dependencies=[Depends(rate_limit("auth"))])
def enable(body: Code, request: Request, p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    """Step 2: prove you hold the secret. Returns the recovery codes ONCE (only their hashes are stored)."""
    with svc.db.session() as s:
        row = s.get(UserMfa, p.user_id)
        if not row or row.enabled:
            raise HTTPException(409, "Start with POST /auth/mfa/setup")
        counter = totp.verify(row.secret, body.code, row.last_counter)
        if counter is None:
            raise HTTPException(422, "That code is not valid. Check the clock on your device and try the next code.")
        codes = totp.new_recovery_codes()
        row.enabled, row.last_counter, row.recovery_hashes = True, counter, [totp.hash_code(c) for c in codes]
    svc.auditor.record("mfa_enabled", tenant_id=p.tenant_id, user_id=p.user_id, ip=request.client.host if request.client else None, request_id=request.state.request_id)
    return {"enabled": True, "recovery_codes": codes}


@router.post("/disable", dependencies=[Depends(rate_limit("auth"))])
def disable(body: Disable, request: Request, p: Principal = Depends(get_principal), svc: Services = Depends(get_svc)):
    """Needs BOTH the password and a current code (or recovery code): a stolen session alone cannot remove the second factor."""
    with svc.db.session() as s:
        u, row = s.get(User, p.user_id), s.get(UserMfa, p.user_id)
        if not row or not row.enabled:
            raise HTTPException(409, "MFA is not enabled")
        if not (u and verify_password(body.password, u.password_hash) and check_second_factor(row, body.code)):
            svc.auditor.record("mfa_disable", tenant_id=p.tenant_id, user_id=p.user_id, outcome="denied", request_id=request.state.request_id)
            raise HTTPException(401, "Password or code is wrong")
        s.delete(row)
    svc.auditor.record("mfa_disabled", tenant_id=p.tenant_id, user_id=p.user_id, request_id=request.state.request_id)
    return {"enabled": False}
