from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RelevantRef(BaseModel):
    """A gold passage: the source file and (optionally) page / sheet / row and a phrase the passage must contain."""

    source: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    contains: Optional[str] = Field(default=None, description="case-insensitive phrase that must occur in the retrieved chunk")


class EvalCase(BaseModel):
    id: str
    question: str = Field(min_length=1, max_length=1000)
    type: Literal["semantic", "exact", "data", "abstain", "intel", "hindi", "compare", "contradiction", "analytics", "parallel"] = "semantic"
    relevant: list[RelevantRef] = []  # gold passages -> Recall@K / Precision@K / MRR
    expected_route: Optional[str] = None
    expected_keywords: list[str] = []  # all must appear in the answer
    expected_count: Optional[int] = None  # exact search occurrence count
    expected_value: Optional[float] = None  # data-agent numeric result
    expected_sources: list[str] = []  # every one of these files must be cited
    forbidden_keywords: list[str] = []  # none may appear in the answer (e.g. a number from an old version)
    answerable: bool = True  # False: the correct behaviour is to abstain (verified == False)


class EvalDataset(BaseModel):
    name: str = "dataset"
    cases: list[EvalCase] = Field(min_length=1, max_length=500)

    @classmethod
    def load(cls, path: str | Path) -> "EvalDataset":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".jsonl":
            return cls(name=p.stem, cases=[EvalCase(**json.loads(line)) for line in text.splitlines() if line.strip()])
        return cls(**json.loads(text))
