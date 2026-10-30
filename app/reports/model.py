from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional


@dataclass
class Doc:
    """A report as a list of simple blocks; renderers turn it into PDF / DOCX / XLSX."""

    title: str
    subtitle: str = ""
    generated_by: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    blocks: list[tuple[str, dict]] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # [{"name","version","kind","ingested_at","hash"}]

    # --- block constructors
    def h(self, text: str, level: int = 1) -> "Doc":
        self.blocks.append(("heading", {"text": text, "level": min(max(level, 1), 3)}))
        return self

    def p(self, text: str) -> "Doc":
        if text and text.strip():
            self.blocks.append(("paragraph", {"text": text}))
        return self

    def bullets(self, items: list[str]) -> "Doc":
        if items:
            self.blocks.append(("bullets", {"items": [str(i) for i in items]}))
        return self

    def table(self, header: list[str], rows: list[list], caption: Optional[str] = None) -> "Doc":
        self.blocks.append(("table", {"header": [str(h) for h in header], "rows": [["" if c is None else c for c in r] for r in rows], "caption": caption}))
        return self

    def chart(self, spec: dict) -> "Doc":
        self.blocks.append(("chart", {"spec": spec}))
        return self

    def note(self, text: str) -> "Doc":
        self.blocks.append(("note", {"text": text}))
        return self

    def add_sources(self, metas: list[dict]) -> "Doc":
        seen = {s["name"] + str(s.get("version")) for s in self.sources}
        for m in metas:
            key = m["name"] + str(m.get("version"))
            if key not in seen:
                seen.add(key)
                self.sources.append({"name": m["name"], "version": m.get("version") or 1, "kind": m.get("kind", ""), "ingested_at": m.get("ingested_at") or m.get("created_at") or "",
                                     "hash": (m.get("content_hash") or "")[:12]})
        return self

    @property
    def timestamp(self) -> str:
        return self.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
