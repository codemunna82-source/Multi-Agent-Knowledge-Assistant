from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Hit:
    chunk_id: str
    source_id: str
    source: str
    location: str
    loc: dict
    text: str  # the matched child chunk (used for citations / excerpts)
    score: float = 0.0  # best cosine similarity over query variants (0 if only found lexically)
    lexical: float = 0.0  # fraction of query terms present in the chunk
    fused: float = 0.0  # reciprocal-rank-fusion score
    rerank: Optional[float] = None
    context: str = ""  # parent passage (possibly compressed) that is given to the LLM
    parent_key: tuple = ()
    suspicious: bool = False  # looks like a prompt-injection attempt
    compressed: bool = False

    @property
    def llm_text(self) -> str:
        return self.context or self.text
