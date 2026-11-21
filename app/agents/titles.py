"""Short conversation titles from the first question, without a model call (no extra latency, cost or data sent anywhere).

'hi, can you please tell me how many days of annual leave employees get?' -> 'How many days of annual leave employees get'.
Greetings and polite filler at the start are dropped, the question mark goes, the first letter is capitalised and the text is cut at a word
boundary. Small talk keeps its own short title. The user can rename a chat at any time (PATCH /conversations/{id})."""
from __future__ import annotations

import re

from . import smalltalk

MAX = 48
_LEAD = re.compile(
    r"^(?:(?:hi+|hello+|hey+|hola|namaste|namaskar|ok(?:ay)?|so|well|please|pls|plz|kindly|bhai|sir|madam|यार|नमस्ते)\b[\s,.:;!-]*)+"
    r"|^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:tell|show|give|explain|help)(?:\s+me)?(?:\s+(?:with|to|about))?\s+"
    r"|^(?:i\s+(?:want|need|would like)\s+to\s+(?:know|find out|understand)\s+)"
    r"|^(?:tell|show|give|explain)\s+me\s+(?:about\s+)?"
    r"|^(?:mujhe|batao|bataiye|bataye)\s+", re.I)
_TRAIL = re.compile(r"[\s?!.,;:।]+$")
_LABEL = {"greeting": "Greeting", "how_are_you": "Greeting", "thanks": "Thanks", "bye": "Goodbye", "identity": "About the assistant", "capabilities": "What can you do?", "ack": "Chat"}


def make_title(question: str) -> str:
    q = " ".join(question.split())
    if not q:
        return "New conversation"
    kind = smalltalk.detect(q)
    if kind:
        return _LABEL[kind]
    t = q
    for _ in range(3):                      # 'hi, please tell me ...' strips in more than one step
        stripped = _LEAD.sub("", t).strip()
        if stripped == t or not stripped:
            break
        t = stripped
    t = _TRAIL.sub("", t) or _TRAIL.sub("", q) or q
    t = t[0].upper() + t[1:]
    if len(t) <= MAX:
        return t
    cut = t[:MAX].rsplit(" ", 1)[0] if " " in t[:MAX] else t[:MAX]
    return cut.rstrip(" ,;:-") + "…"
