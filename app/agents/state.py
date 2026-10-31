from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """Checkpointed graph state: JSON-serialisable only. Heavy / non-serialisable objects (scope, principal, stores) live in RunCtx."""

    rid: str
    question: str
    query: str  # question after follow-up resolution
    route: str
    term: Optional[str]
    quoted: bool
    plan: dict  # how the supervisor decided {"method": "rules|llm", ...}
    evidence: list[dict]
    draft: dict  # answer being built
    verification: dict  # {"status": "pass|retry|fail", "issues": [...]}
    attempt: int
    branch: dict  # (fan-out) one sub-question with its route, handed to a parallel branch
    branches: Annotated[list[dict], operator.add]  # (fan-out) results of the parallel branches, merged by the merge node
    trace: Annotated[list[str], operator.add]
    result: dict
    followups: list[str]


@dataclass
class RunCtx:
    scope: Any
    principal: Any
    req: Any  # AskRequest
    opts: Any  # rag.Resolved
    history: list[dict] = field(default_factory=list)  # [{"question","answer","route","term"}] oldest->newest (bounded window)
    summary: Optional[str] = None  # rolling summary of older turns
    notes: list = field(default_factory=list)  # user-saved memory notes relevant to this question (opt-in long-term memory)
    usage: Any = None
    on_token: Any = None  # optional callable(str | None): receives provider tokens of the draft answer; None = a new draft starts (discard the previous one)
    t0: float = field(default_factory=time.perf_counter)
    _metas: Optional[list] = None

    def sources(self, k, ids: Optional[list[str]] = None) -> list[dict]:
        """ACL-filtered sources (hidden documents are indistinguishable from missing ones)."""
        st = k.store(self.scope)
        metas = st.list_sources(self.principal)
        want = self.req.source_ids if ids is None else ids
        if want is not None:
            unknown = set(want) - {m["id"] for m in metas}
            if unknown:
                raise KeyError(f"Unknown source id(s): {', '.join(sorted(unknown))}")
            metas = [m for m in metas if m["id"] in want]
        return metas

    @property
    def last(self) -> Optional[dict]:
        return self.history[-1] if self.history else None
