"""Event / date timeline extraction: every date mentioned in the text becomes a dated event (the sentence it appears in) with its source
location, sorted chronologically. Rule-based (English month names, ISO, numeric day/month/year, quarters, explicit years); Hindi and other
scripts' date words are not parsed (documented limitation)."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..core import Unit, format_loc

MONTHS = {m: i for i, names in enumerate(
    ["jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july", "aug august", "sep sept september", "oct october", "nov november", "dec december"], 1) for m in names.split()}
_M = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("dmy_text", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_M})\.?,?\s+(\d{{4}})\b", re.I)),
    ("mdy_text", re.compile(rf"\b({_M})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)),
    ("num", re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")),
    ("month_year", re.compile(rf"\b({_M})\.?\s+(\d{{4}})\b", re.I)),
    ("quarter", re.compile(r"\bQ([1-4])\s*(?:FY)?\s*(\d{4})\b", re.I)),
    ("year", re.compile(r"\b(?:in|since|during|by|from|until|till|before|after|year|FY|fiscal)\s+((?:19|20)\d{2})\b", re.I)),
]
PREC = {"day": 0, "month": 1, "quarter": 2, "year": 3}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])|\n+")


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, dayfirst: bool = True) -> list[dict]:
    """-> [{"date": ISO, "precision", "raw", "ambiguous"}] in order of appearance; overlapping matches keep the most specific."""
    spans: list[tuple[int, int]] = []
    out: list[tuple[int, dict]] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in spans):
                continue
            d: Optional[date] = None
            prec, amb = "day", False
            g = m.groups()
            if kind == "iso":
                d = _mk(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "dmy_text":
                d = _mk(int(g[2]), MONTHS[g[1].lower()], int(g[0]))
            elif kind == "mdy_text":
                d = _mk(int(g[2]), MONTHS[g[0].lower()], int(g[1]))
            elif kind == "num":
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                if a > 12:
                    d = _mk(y, b, a)
                elif b > 12:
                    d = _mk(y, a, b)
                else:
                    amb = a != b
                    d = _mk(y, b, a) if dayfirst else _mk(y, a, b)
            elif kind == "month_year":
                d, prec = _mk(int(g[1]), MONTHS[g[0].lower()], 1), "month"
            elif kind == "quarter":
                d, prec = _mk(int(g[1]), (int(g[0]) - 1) * 3 + 1, 1), "quarter"
            elif kind == "year":
                d, prec = _mk(int(g[0]), 1, 1), "year"
            if d is None:
                continue
            spans.append((m.start(), m.end()))
            raw = m.group(0)
            out.append((m.start(), {"date": d.isoformat(), "precision": prec, "raw": raw if kind != "year" else g[0], "ambiguous": amb}))
    return [x for _, x in sorted(out, key=lambda t: t[0])]


def build_timeline(items: list[tuple[dict, Unit]], dayfirst: bool = True, max_events: int = 500) -> list[dict]:
    """items = [(source_meta, unit)] -> chronologically sorted, de-duplicated events with citations."""
    events, seen = [], set()
    for meta, unit in items:
        structured = "row" in unit.loc or "path" in unit.loc
        sents = [unit.text] if structured else [s for s in _SENT.split(re.sub(r"(?<!\n)\n(?!\n)", " ", unit.text)) if s.strip()]
        for sent in sents:
            for d in find_dates(sent, dayfirst):
                key = (d["date"], d["precision"], re.sub(r"\W+", " ", sent.lower())[:120])
                if key in seen:
                    continue
                seen.add(key)
                events.append({**d, "event": " ".join(sent.split())[:260], "source_id": meta["id"], "source": meta["name"], "location": format_loc(unit.loc), "loc": unit.loc})
    events.sort(key=lambda e: (e["date"], PREC[e["precision"]], e["source"]))
    return events[:max_events]
