"""TOTP (RFC 6238) / HOTP (RFC 4226), implemented with the standard library only, plus single-use recovery codes.
Verified against the RFC 6238 appendix B test vectors in tests/test_mfa.py."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # accept the previous/next 30 s step too (clock drift)


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")  # 160 bits, the RFC 4226 recommendation


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret: str, counter: int, digits: int = DIGITS, algo: str = "sha1") -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", counter), getattr(hashlib, algo)).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp(secret: str, at: Optional[float] = None, digits: int = DIGITS, algo: str = "sha1") -> str:
    return hotp(secret, int((time.time() if at is None else at) // STEP), digits, algo)


def verify(secret: str, code: str, last_counter: int = 0, at: Optional[float] = None) -> Optional[int]:
    """-> the matched time-step counter, or None. A counter <= `last_counter` is refused, so a code (even one observed over the shoulder) works once."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = int((time.time() if at is None else at) // STEP)
    hit = None
    for c in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(hotp(secret, c), code) and c > last_counter:  # no early exit: constant work for every candidate
            hit = c
    return hit


def provisioning_uri(secret: str, account: str, issuer: str = "Multi-Agent Knowledge Assistant") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def new_recovery_codes(n: int = 10) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def use_recovery(hashes: list[str], code: str) -> Optional[list[str]]:
    """-> the remaining hashes if `code` was valid (and is now spent), else None."""
    h = hash_code(code)
    if not any(hmac.compare_digest(h, x) for x in hashes):
        return None
    return [x for x in hashes if not hmac.compare_digest(h, x)]
