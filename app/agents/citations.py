"""Citation validation (Verification Agent): every citation must point at a real location of a real source the caller can read, and its excerpt
must actually occur there. Page, sheet/row, paragraph and line citations are checked against the stored extracted units."""
from __future__ import annotations

import re

from ..core import stem, tokenize

MIN_COVERAGE = 0.6
WINDOW = 8  # a retrieved chunk can start at one unit (e.g. a heading) and continue into the next ones; the excerpt is checked against that window


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _toks(text: str) -> list[str]:
    return [stem(t) for t in tokenize(_THOUSANDS.sub("", text), drop_stop=False)]


def _key(loc: dict) -> tuple:
    return tuple(sorted((k, v) for k, v in loc.items() if k in ("page", "sheet", "row", "paragraph", "line", "table", "path", "image")))


class CitationChecker:
    """Lazy per-request index: source id -> ([location key per unit], [stemmed tokens per unit]) in document order."""

    def __init__(self, store, principal=None):
        self.store, self.principal = store, principal
        self._idx: dict[str, dict | None] = {}

    def _index(self, sid: str):
        if sid not in self._idx:
            meta = self.store.get_source(sid, self.principal)
            if not meta:  # unknown or not visible: indistinguishable
                self._idx[sid] = None
            else:
                keys, toks = [], []
                for _, u in self.store.iter_units([sid]):
                    keys.append(_key(u.loc))
                    toks.append(set(_toks(u.text)))
                self._idx[sid] = (keys, toks)
        return self._idx[sid]

    def check(self, c: dict) -> tuple[str, str]:
        """-> (status, reason) with status in valid | invalid | unchecked."""
        sid, loc = c.get("source_id"), c.get("loc")
        if sid in (None, "web") or not loc:
            return "unchecked", "no machine-readable location"
        idx = self._index(sid)
        if idx is None:
            return "invalid", "source not found or not accessible"
        keys, per_unit = idx
        key = _key(loc)
        starts = [i for i, k in enumerate(keys) if k == key]
        if not starts:
            return "invalid", f"location {c.get('location')} does not exist in the source"
        ex = _toks(c.get("excerpt", ""))[:60]
        if not ex:
            return "valid", ""
        head = ex[:4]

        def starts_here(i: int) -> bool:
            """The excerpt begins inside the cited unit, or the cited unit (e.g. a heading) is the beginning of the excerpt."""
            u = per_unit[i]
            return sum(1 for t in head if t in u) >= 0.75 * len(head) or (0 < len(u) <= 6 and u <= set(ex[: len(u) + 1]))

        starts = [i for i in starts if starts_here(i)]
        if not starts:
            return "invalid", f"the cited text does not start at {c.get('location')}"
        cov = max(sum(1 for t in ex if t in win) / len(ex) for win in (set().union(*per_unit[i:i + WINDOW]) for i in starts))
        need = 0.5 if "row" in loc and "page" not in loc else MIN_COVERAGE  # spreadsheet cells are re-formatted (1,200.50 -> 1200.5)
        return ("valid", "") if cov >= need else ("invalid", f"excerpt not found at {c.get('location')} (coverage {cov:.0%})")


def validate(store, principal, citations: list[dict]) -> tuple[list[dict], dict]:
    """-> (citations that passed or could not be checked, report). Invalid citations are removed from the answer and listed in the report."""
    chk = CitationChecker(store, principal)
    keep, invalid, valid, unchecked = [], [], 0, 0
    for c in citations:
        st, why = chk.check(c)
        if st == "invalid":
            invalid.append({"source": c.get("source"), "location": c.get("location"), "reason": why})
            continue
        valid += st == "valid"
        unchecked += st == "unchecked"
        keep.append(c)
    checked = valid + len(invalid)
    return keep, {"total": len(citations), "checked": checked, "valid": valid, "invalid": invalid, "unchecked": unchecked, "accuracy": round(valid / checked, 4) if checked else None}
