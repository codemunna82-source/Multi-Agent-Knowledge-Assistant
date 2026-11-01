"""Encryption at rest for small secrets stored in the database (TOTP seeds). Fernet (AES-128-CBC + HMAC-SHA256) with a key from MKA_DATA_KEY.

 - key set      -> new values are stored as "enc1:<token>"
 - key not set  -> new values are stored as given (plaintext); a startup warning is logged by the caller
 - values written without a key stay readable after a key is added (migration path); an "enc1:" value without the key is an error, never a guess.
Generate a key:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Losing the key makes the stored secrets unreadable (affected users must re-enrol MFA); rotating needs re-encryption (not automated)."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings

PREFIX = "enc1:"


class SecretBoxError(Exception):
    pass


def _fernet(s: Settings):
    key = s.secret("data_key")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise SecretBoxError("MKA_DATA_KEY is not a valid Fernet key (32 url-safe base64 bytes)") from e


def seal(s: Settings, plain: str) -> str:
    f = _fernet(s)
    return PREFIX + f.encrypt(plain.encode()).decode() if f else plain


def open_(s: Settings, stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored
    f = _fernet(s)
    if not f:
        raise SecretBoxError("Stored secret is encrypted but MKA_DATA_KEY is not set")
    try:
        return f.decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise SecretBoxError("Stored secret cannot be decrypted with the configured MKA_DATA_KEY") from e
