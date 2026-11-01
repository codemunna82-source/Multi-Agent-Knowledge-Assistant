from __future__ import annotations

import re
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


HEADING = re.compile(
    r"^(?:#{1,6}\s+\S.*"                                                    # markdown
    r"|(?:\d+\.)+\d*\)?\s+[A-Z\u0900-\u097F]\S.{0,90}"                       # 1.2 Leave policy
    r"|\d+[.)]\s+[A-Z]\S.{0,90}"                                            # 3) Termination
    r"|(?:Article|Section|Clause|Chapter|Appendix|Annexure)\s+[\w.-]+\b.{0,80}"  # Clause 8 ...
    r"|[A-Z][A-Z0-9 ,&/'-]{3,60})$"                                          # ALL CAPS TITLE
)


def _is_heading(line: str) -> bool:
    line = line.strip()
    return 0 < len(line) <= 100 and not line.endswith((".", ",", ";")) and bool(HEADING.match(line))


def _sections(text: str) -> list[tuple[Optional[str], str]]:
    """Split text at heading lines -> [(heading or None, section text incl. its heading line)]."""
    out: list[tuple[Optional[str], list[str]]] = [(None, [])]
    for line in text.split("\n"):
        if _is_heading(line):
            out.append((line.strip(), [line]))
        else:
            out[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in out if "\n".join(b).strip()]


def chunk_units(units: list[Unit], size: int = 1000, overlap: int = 150, structure: bool = False) -> list[Chunk]:
    """Merge small adjacent units (e.g. table rows) up to `size`; split oversized units with overlap.
    A chunk always starts/ends on unit boundaries, so its location range is exact.

    structure=True additionally respects headings: a heading always starts a new chunk, and a section longer than `size` is split with its
    heading repeated at the top of every piece (so a late piece still says which clause/section it belongs to). u0/u1 keep pointing at the
    ORIGINAL unit indexes, so parent expansion and citations are unchanged."""
    chunks: list[Chunk] = []
    buf: list[tuple[int, Unit]] = []
    blen = 0

    def flush():
        nonlocal buf, blen
        if buf:
            chunks.append(Chunk("\n".join(u.text for _, u in buf), buf[0][1].loc, buf[-1][1].loc if len(buf) > 1 else None, buf[0][0], buf[-1][0]))
        buf, blen = [], 0

    pieces: list[tuple[int, Unit, Optional[str]]] = []  # (original index, unit, heading it starts)
    for i, u in enumerate(units):
        if structure and "\n" in u.text:
            for head, body in _sections(u.text):
                pieces.append((i, Unit(body, u.loc), head))
        else:
            pieces.append((i, u, u.text.strip().split("\n", 1)[0].strip() if structure and _is_heading(u.text.strip().split("\n", 1)[0]) else None))

    for i, u, head in pieces:
        if len(u.text) > size:
            flush()
            ws = _windows(u.text, size, overlap)
            for n, w in enumerate(ws):
                txt = f"{head}\n{w}" if head and n > 0 and not w.startswith(head) else w
                chunks.append(Chunk(txt, u.loc, None, i, i))
            continue
        # never merge across pages / sheets / tables / sections: the chunk's location (citation + filters) must be exact
        if blen + len(u.text) + 1 > size or (buf and any(buf[-1][1].loc.get(k) != u.loc.get(k) for k in _BOUNDARY)) or (structure and head and buf):
            flush()
        buf.append((i, u))
        blen += len(u.text) + 1
    flush()
    return chunks
