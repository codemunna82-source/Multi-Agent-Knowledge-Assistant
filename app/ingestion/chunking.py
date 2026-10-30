from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core import Unit


_BOUNDARY = ("page", "sheet", "table", "section")


@dataclass
class Chunk:
    text: str
    loc: dict
    loc_end: Optional[dict] = None
    u0: int = 0  # index of first unit covered (parent span)
    u1: int = 0  # index of last unit covered (inclusive)


def _windows(text: str, size: int, overlap: int) -> list[str]:
    out, i, n = [], 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:  # prefer breaking on whitespace
            cut = text.rfind(" ", i + size // 2, end)
            end = cut if cut > i else end
        out.append(text[i:end].strip())
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return [w for w in out if w]


def chunk_units(units: list[Unit], size: int = 1000, overlap: int = 150) -> list[Chunk]:
    """Merge small adjacent units (e.g. table rows) up to `size`; split oversized units with overlap.
    A chunk always starts/ends on unit boundaries, so its location range is exact."""
    chunks: list[Chunk] = []
    buf: list[Unit] = []
    idx: list[int] = []
    blen = 0

    def flush():
        nonlocal buf, idx, blen
        if buf:
            chunks.append(Chunk("\n".join(u.text for u in buf), buf[0].loc, buf[-1].loc if len(buf) > 1 else None, idx[0], idx[-1]))
        buf, idx, blen = [], [], 0

    for i, u in enumerate(units):
        if len(u.text) > size:
            flush()
            chunks.extend(Chunk(w, u.loc, None, i, i) for w in _windows(u.text, size, overlap))
            continue
        # never merge across pages / sheets / tables / sections: the chunk's location (citation + filters) must be exact
        if blen + len(u.text) + 1 > size or (buf and any(buf[-1].loc.get(k) != u.loc.get(k) for k in _BOUNDARY)):
            flush()
        buf.append(u)
        idx.append(i)
        blen += len(u.text) + 1
    flush()
    return chunks
