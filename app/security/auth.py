"""Passwords (bcrypt), JWT access tokens, principals and role permissions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from ..config import Settings

ROLES = ("viewer", "editor", "admin")
# permission -> minimum role
PERMISSIONS = {
    "ask": "viewer",
    "read": "viewer",
    "ingest": "editor",
    "delete_own": "editor",
    "delete_any": "admin",
    "manage_users": "admin",
    "audit": "admin",
    "settings": "admin",
    "evaluate": "editor",
    "purge": "admin",
}
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
    now = datetime.now(timezone.utc)
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
