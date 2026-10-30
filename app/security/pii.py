"""Sensitive-data helpers for memory: detect/redact obvious secrets and personal identifiers.

This is a pattern-based safety net (emails, phone numbers, payment cards with a Luhn check, national-ID-like numbers, API keys, JWTs,
passwords written as "password: ..."). It reduces accidental storage; it is NOT a guarantee that no personal data is ever stored."""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}(?!\w)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)|(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")  # US SSN, Indian Aadhaar-style
SECRET = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})")
PASSWORD = re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_ -]?key|token|pin)\b\s*(?:is|=|:)\s*\S+")


def _luhn(digits: str) -> bool:
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        s += d
        alt = not alt
    return s % 10 == 0


def _card_hits(text: str) -> list[re.Match]:
    return [m for m in CARD.finditer(text) if 13 <= len(re.sub(r"\D", "", m.group(0))) <= 19 and _luhn(re.sub(r"\D", "", m.group(0)))]


def findings(text: str) -> list[str]:
    out = []
    if SECRET.search(text) or PASSWORD.search(text):
        out.append("secret or password")
    if _card_hits(text):
        out.append("payment card number")
    if SSN.search(text):
        out.append("national ID number")
    if EMAIL.search(text):
        out.append("email address")
    if any(len(re.sub(r"\D", "", m.group(0))) >= 9 for m in PHONE.finditer(text)):
        out.append("phone number")
    return out


def looks_sensitive(text: str) -> bool:
    return bool(findings(text))


def redact(text: str) -> str:
    for m in reversed(_card_hits(text)):
        text = text[:m.start()] + "[card]" + (" " if m.group(0).endswith((" ", "-")) else "") + text[m.end():]
    text = SECRET.sub("[secret]", text)
    text = PASSWORD.sub(lambda m: m.group(0).split()[0] + " [redacted]", text)
    text = SSN.sub("[id]", text)
    text = EMAIL.sub("[email]", text)
    return PHONE.sub(lambda m: "[phone]" if len(re.sub(r"\D", "", m.group(0))) >= 9 else m.group(0), text)
