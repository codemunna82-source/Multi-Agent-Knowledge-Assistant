"""Shared types and helpers: units, locations, tokenisation, errors."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


class IngestError(Exception):
    """Raised for any user-visible ingestion failure (unsupported, corrupt, empty, blocked URL...)."""


class ProviderError(Exception):
    """Raised when an embedding/LLM API call fails."""


@dataclass
class Unit:
    """Smallest addressable piece of extracted text (a page, a row, a paragraph...)."""

    text: str
    loc: dict


@dataclass
class Extracted:
    units: list[Unit]
    title: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    tables: list[dict] = field(default_factory=list)  # [{"location": {...}, "header": [...], "rows": [[...]]}] structured, NOT searchable text


def format_loc(loc: dict, loc_end: Optional[dict] = None) -> str:
    """Human readable location, e.g. "page 3", "sheet 'Q1', row 12", "rows 2-9"."""
    if not loc:
        return "document"
    if "url" in loc and len(loc) == 1:
        return loc["url"]

    def rng(key: str, label: str, plural: str) -> Optional[str]:
        if key not in loc:
            return None
        a, b = loc[key], (loc_end or {}).get(key)
        if b is not None and b != a:
            return f"{plural} {a}-{b}"
        return f"{label} {a}"

    parts: list[str] = []
    if "sheet" in loc:
        parts.append(f"sheet '{loc['sheet']}'")
    if "table" in loc:
        parts.append(f"table {loc['table']}")
    for key, label, plural in (("page", "page", "pages"), ("row", "row", "rows"), ("paragraph", "paragraph", "paragraphs"), ("line", "line", "lines")):
        s = rng(key, label, plural)
        if s:
            parts.append(s)
    if "path" in loc:
        parts.append(f"path {loc['path']}")
    if "image" in loc:
        parts.append("image caption" if loc.get("caption") else "image (OCR)")
    out = ", ".join(parts) or "document"
    if loc.get("section"):
        out += f" (section: {loc['section']})"
    return out


STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how i if in into is it its of on or that the their there these this to was were what when where which who whom why will with you your my me do does did can could should would about than then so such not no
    का के की को में से पर और है हैं था थी थे यह वह इस उस एक भी तो ही कि जो कर लिए ने हो गया गई गए रहा रही रहे या इन उन
    """.split()
)

_W = r"[\w\u0300-\u036f\u0900-\u0dff\u0e00-\u0eff\u0f00-\u0fff\u1ab0-\u1aff\u20d0-\u20ff]"  # \w + combining marks (Indic, Thai, ...)
_TOKEN = re.compile(rf"{_W}+(?:[-']{_W}+)*", re.UNICODE)  # unicode-aware: Hindi, Arabic, accented Latin, CJK runs, ...


NOSPACE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f]")  # CJK, Hangul, Thai: no spaces between words


def _split_nospace(tok: str) -> list[str]:
    """Words are not delimited in these scripts: index overlapping character bigrams (the standard cheap approach), single characters stay as they are."""
    out: list[str] = []
    run = ""
    for ch in tok + " ":
        if NOSPACE.match(ch):
            run += ch
            continue
        if run:
            out.extend([run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
            run = ""
        if ch != " ":
            out.append(ch)
    return ["".join(out)] if out and not any(NOSPACE.match(c) for c in "".join(out)) else out


def tokenize(text: str, drop_stop: bool = True) -> list[str]:
    toks: list[str] = []
    for t in _TOKEN.findall(text):
        t = t.lower()
        toks.extend(_split_nospace(t) if NOSPACE.search(t) else [t])
    if drop_stop:
        toks = [t for t in toks if t not in STOPWORDS]
    return toks


def stem(tok: str) -> str:
    """Very light plural stripping (consistent on both sides of every comparison): employees->employee, policies->policy, boxes->box."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith(("sses", "xes", "zes", "ches", "shes")):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok
