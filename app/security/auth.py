"""Passwords (bcrypt), JWT access tokens, principals and role permissions."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from ..config import Settings

ROLES = ("user", "manager", "admin")
LEGACY_ROLES = {"viewer": "user", "editor": "manager"}  # v2.0 names, still accepted at the API boundary
# permission -> minimum role
PERMISSIONS = {
    "ask": "user", "read": "user", "search": "user", "summarize": "user", "compare": "user", "analytics": "user", "web": "user", "report": "user", "memory": "user",
    "ingest": "manager", "delete_own": "manager", "share": "manager", "evaluate": "manager",
    "delete_any": "admin", "manage_users": "admin", "audit": "admin", "settings": "admin", "purge": "admin",
}


def normalize_role(role: str) -> str:
    r = LEGACY_ROLES.get(role, role)
    if r not in ROLES:
        raise ValueError("role must be user, manager or admin")
    return r
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=10))


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    email: str = ""

    def can(self, permission: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(PERMISSIONS[permission])


ANONYMOUS = Principal(user_id="anonymous", tenant_id="default", role="admin", email="anonymous@local")


def validate_password(pw: str) -> None:
    if len(pw) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(pw.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes")


def hash_password(pw: str) -> str:
    validate_password(pw)
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str | None) -> bool:
    """Constant-ish time: always runs one bcrypt comparison, even for unknown users."""
    h = hashed.encode() if hashed else _DUMMY_HASH
    try:
        ok = bcrypt.checkpw(pw.encode()[:72], h)
    except ValueError:
        return False
    return ok and hashed is not None


def create_token(s: Settings, user) -> tuple[str, int]:
    ttl = timedelta(minutes=s.access_token_minutes)
    now = datetime.now(UTC)
    payload = {"sub": user.id, "tid": user.tenant_id, "role": user.role, "email": user.email,
               "jti": uuid.uuid4().hex, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, s.jwt_key(), algorithm=s.jwt_algorithm), int(ttl.total_seconds())


def decode_token(s: Settings, token: str) -> dict:
    try:
        return jwt.decode(token, s.jwt_key(), algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "tid", "jti"]})
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token expired") from e
    except jwt.PyJWTError as e:
        raise AuthError("Invalid token") from e



# ----------------------------------------------------------------------------- refresh tokens (rotation + reuse detection)
class RefreshReuse(AuthError):
    """A refresh token that was already rotated was presented again: the whole token family has been revoked."""

    def __init__(self, msg: str, user_id: str | None = None, tenant_id: str | None = None):
        super().__init__(msg)
        self.user_id, self.tenant_id = user_id, tenant_id


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh(session, s: Settings, user_id: str, family_id: str | None = None, ip: str | None = None) -> str:
    from ..db import RefreshToken

    token = secrets.token_urlsafe(48)
    session.add(RefreshToken(token_hash=_h(token), user_id=user_id, family_id=family_id or uuid.uuid4().hex, ip=ip,
                             expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days)))
    return token


def rotate_refresh(db, s: Settings, token: str, ip: str | None = None):
    """-> (User, new_refresh_token). Old token is revoked; presenting a revoked token revokes the family (theft detection)."""
    from sqlalchemy import update

    from ..db import RefreshToken, User

    reuse = False
    with db.session() as ses:
        row = ses.get(RefreshToken, _h(token))
        if row is None:
            raise AuthError("Invalid refresh token")
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if row.revoked_at is not None:
            ses.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
            owner = ses.get(User, row.user_id)
            reuse, who = True, (row.user_id, owner.tenant_id if owner else None)
        elif exp < datetime.now(UTC):
            raise AuthError("Refresh token expired")
        else:
            user = ses.get(User, row.user_id)
            if not user or not user.is_active:
                raise AuthError("Account disabled or removed")
            new = issue_refresh(ses, s, user.id, row.family_id, ip)
            row.revoked_at, row.replaced_by = datetime.now(UTC), _h(new)
            return user, new
    if reuse:  # committed above; raise outside the transaction so the revocation sticks
        raise RefreshReuse("Refresh token reuse detected; all sessions of this login were revoked", *who)
    raise AuthError("Invalid refresh token")


def revoke_refresh(db, token: str) -> bool:
    from sqlalchemy import update

    from ..db import RefreshToken

    with db.session() as ses:
        row = ses.get(RefreshToken, _h(token))
        if not row:
            return False
        ses.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
        return True
