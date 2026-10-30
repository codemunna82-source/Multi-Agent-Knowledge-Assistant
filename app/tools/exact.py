"""Exact / literal search over the COMPLETE extracted corpus (never over a sampled subset).

Counting rules (also returned to the caller so they are never implicit):
  * Unicode NFKC normalised; whitespace inside the term matches any run of whitespace (incl. line breaks)
  * case-insensitive by default (case_sensitive=true to change)
  * whole-word by default: "Ann" does not match "Annual" (whole_word=false for substring matching); scripts without word delimiters (CJK, Thai) always use substring matching
  * every non-overlapping occurrence counts, in every page / row / paragraph; a match that spans a page
    or row boundary is not counted
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from ..core import NOSPACE, Unit, format_loc


@dataclass
class ExactResult:
    term: str
    count: int = 0
    units_with_match: int = 0
    by_source: dict = field(default_factory=dict)  # source_id -> {"name":..., "count":...}
    matches: list = field(default_factory=list)  # capped list of excerpts
    truncated: bool = False
    rules: str = ""


def build_pattern(term: str, case_sensitive: bool = False, whole_word: bool = True) -> re.Pattern:
    term = unicodedata.normalize("NFKC", term).strip()
    if not term:
        raise ValueError("empty search term")
    body = r"\s+".join(re.escape(p) for p in term.split())
    if whole_word and NOSPACE.search(term):
        whole_word = False  # CJK/Thai have no word delimiters: a "whole word" match is meaningless there, substring matching is the only sensible rule
    if whole_word:
        pre = r"(?<!\w)" if re.match(r"\w", term[0]) else ""
        post = (r"(?!\w)" + (r"(?!\.\d)" if term[-1].isdigit() else "")) if re.match(r"\w", term[-1]) else ""
        body = pre + body + post
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


def exact_search(items: Iterable[tuple[dict, Unit]], term: str, *, case_sensitive: bool = False, whole_word: bool = True,
                 max_excerpts: int = 50, context: int = 90) -> ExactResult:
    pat = build_pattern(term, case_sensitive, whole_word)
    res = ExactResult(term=term.strip())
    res.rules = (f"{'case-sensitive' if case_sensitive else 'case-insensitive'}, {'whole-word' if whole_word else 'substring'} matching; "
                 "all non-overlapping occurrences in the full extracted text are counted; matches spanning a page/row boundary are not")
    for meta, unit in items:
        text = unicodedata.normalize("NFKC", unit.text)
        found = list(pat.finditer(text))
        if not found:
            continue
        res.count += len(found)
        res.units_with_match += 1
        entry = res.by_source.setdefault(meta["id"], {"name": meta["name"], "count": 0})
        entry["count"] += len(found)
        for m in found:
            if len(res.matches) >= max_excerpts:
                res.truncated = True
                break
            a, b = max(0, m.start() - context), min(len(text), m.end() + context)
            excerpt = ("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")
            res.matches.append({"source_id": meta["id"], "source": meta["name"], "location": format_loc(unit.loc), "loc": unit.loc, "excerpt": excerpt})
    return res
