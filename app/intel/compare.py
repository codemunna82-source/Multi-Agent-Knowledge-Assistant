"""Document comparison and change detection: sentence-level alignment of two texts (or two versions of one document).

difflib aligns the normalised sentence sequences (exact matches first); inside a replaced block sentences are paired by similarity,
so an edit such as "25 days" -> "30 days" is reported as a *change* with the numbers that moved, not as a removal plus an addition."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..agents.common import split_sentences
from ..core import tokenize

MAX_SEGMENTS = 20000
NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")


def segments(units, structured: bool = False) -> list[tuple[dict, str]]:
    """[(loc, sentence)] for every unit (sentence split; row/line structured units stay whole)."""
    out = []
    for u in units:
        for s in ([u.text.strip()] if structured else split_sentences(u.text)):
            if len(s) >= 3:
                out.append((u.loc, s))
    return out


def _key(s: str) -> str:
    return " ".join(tokenize(s, drop_stop=False))


def numbers(text: str) -> list[str]:
    return [n.replace(",", "").rstrip(".") for n in NUM.findall(text)]


def _pair_block(a_idx, b_idx, a, b, min_ratio=0.5, cap=150):
    pairs, used = [], set()
    for i in a_idx[:cap]:
        best, best_r = None, min_ratio
        for j in b_idx[:cap]:
            if j in used:
                continue
            r = SequenceMatcher(None, a[i][2], b[j][2], autojunk=False).quick_ratio()
            if r >= best_r:
                r = SequenceMatcher(None, a[i][2], b[j][2], autojunk=False).ratio()
                if r >= best_r:
                    best, best_r = j, r
        if best is not None:
            used.add(best)
            pairs.append((i, best, best_r))
    return pairs


def compare_segments(sa: list[tuple[dict, str]], sb: list[tuple[dict, str]], max_items: int = 50) -> dict:
    truncated = len(sa) > MAX_SEGMENTS or len(sb) > MAX_SEGMENTS
    sa, sb = sa[:MAX_SEGMENTS], sb[:MAX_SEGMENTS]
    a = [(loc, s, _key(s)) for loc, s in sa]
    b = [(loc, s, _key(s)) for loc, s in sb]
    ops = SequenceMatcher(None, [x[2] for x in a], [x[2] for x in b], autojunk=False).get_opcodes()
    same = 0
    changed, added, removed = [], [], []
    ent = lambda x: {"text": x[1], "loc": x[0]}  # noqa: E731
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            same += i2 - i1
        elif tag == "delete":
            removed += [ent(a[i]) for i in range(i1, i2)]
        elif tag == "insert":
            added += [ent(b[j]) for j in range(j1, j2)]
        else:
            pairs = _pair_block(list(range(i1, i2)), list(range(j1, j2)), a, b)
            pa, pb = {p[0] for p in pairs}, {p[1] for p in pairs}
            for i, j, r in pairs:
                na, nb = numbers(a[i][1]), numbers(b[j][1])
                only_a, only_b = [n for n in na if n not in nb], [n for n in nb if n not in na]
                changed.append({"before": ent(a[i]), "after": ent(b[j]), "similarity": round(r, 3), "number_changes": [{"from": x, "to": y} for x, y in zip(only_a, only_b)]})
            removed += [ent(a[i]) for i in range(i1, i2) if i not in pa]
            added += [ent(b[j]) for j in range(j1, j2) if j not in pb]
    total = max(len(a), len(b)) or 1
    return {"summary": {"segments_a": len(a), "segments_b": len(b), "unchanged": same, "changed": len(changed), "added": len(added), "removed": len(removed),
                        "similarity": round(same / total, 4)},
            "changed": changed[:max_items], "added": added[:max_items], "removed": removed[:max_items], "truncated": truncated}


def compare_units(units_a, units_b, structured: bool = False, max_items: int = 50) -> dict:
    return compare_segments(segments(units_a, structured), segments(units_b, structured), max_items)
