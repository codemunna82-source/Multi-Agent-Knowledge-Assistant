"""Operational progress reporting for streaming: pipeline and agent code call `stage("rerank")` at the moment a stage starts.
The hook lives in a ContextVar (copied into node threads by call_with_timeout), so non-streaming requests cost one ContextVar read."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Callable, Optional

_hook: ContextVar[Optional[Callable[[str], None]]] = ContextVar("mka_stage_hook", default=None)

LABELS = {
    "understand": "Understanding your question", "strategy": "Choosing a retrieval strategy", "retrieve": "Searching documents", "grade": "Evaluating relevance",
    "rerank": "Reranking retrieved chunks", "generate": "Generating answer", "verify": "Checking the answer against the sources", "exact": "Searching for exact matches",
    "data": "Analysing your data", "web": "Searching the web", "read": "Reading the documents",
}
NODE_STAGE = {"supervisor": "understand", "strategy": "strategy", "exact": "exact", "data": "data", "web": "web", "verify": "verify", "summarize": "read", "compare": "read",
              "semantic": "retrieve", "document_search": "retrieve"}


def set_hook(fn: Optional[Callable[[str], None]]):
    return _hook.set(fn)


def stage(name: str) -> None:
    fn = _hook.get()
    if fn is not None:
        try:
            fn(name)
        except Exception:  # noqa: BLE001 - progress reporting must never break a request
            pass
