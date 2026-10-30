"""Assistant: owns the compiled graph, checkpointer, tool registry and per-request run contexts."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

from langgraph.checkpoint.memory import MemorySaver

from ..providers import Usage
from ..rag import RAGPipeline, resolve
from ..schemas import AskRequest, AskResponse
from ..storage import Scope
from .graph import build_graph
from .nodes import Agents
from .state import RunCtx
from .tools import ToolRegistry

log = logging.getLogger("mka.agent")


def make_checkpointer(settings):
    kind = settings.checkpoint_backend
    if kind == "memory":
        return MemorySaver(), None
    if kind == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = Path(settings.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return SqliteSaver(sqlite3.connect(str(path / "checkpoints.db"), check_same_thread=False)), None
    if kind == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        dsn = settings.db_url.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
        pool = ConnectionPool(dsn, max_size=5, kwargs={"autocommit": True, "row_factory": dict_row}, open=True)
        saver = PostgresSaver(pool)
        saver.setup()
        return saver, pool
    raise ValueError(f"Unknown checkpoint backend '{kind}'")


class Assistant:
    def __init__(self, knowledge, checkpointer=None):
        self.k = knowledge
        self.pipeline = RAGPipeline(knowledge)
        self.tools = ToolRegistry(self)
        self.agents = Agents(self)
        self._pool = None
        if checkpointer is None:
            checkpointer, self._pool = make_checkpointer(knowledge.settings)
        self.checkpointer = checkpointer
        self.graph = build_graph(self.agents, checkpointer)
        self._ctx: dict[str, RunCtx] = {}
        self._threads: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ memory / lifecycle
    @staticmethod
    def thread_id(scope: Scope, user_id: str, conversation_id: str) -> str:
        return f"{scope.key}:{user_id}:{conversation_id}"

    def forget(self, scope: Scope, conversation_id: str, user_id: Optional[str] = None) -> None:
        with self._lock:
            tids = [t for t in self._threads.get(scope.key, set()) if t.endswith(f":{conversation_id}") and (user_id is None or f":{user_id}:" in t)]
        for t in tids:
            self._drop_thread(scope, t)

    def forget_workspace(self, scope: Scope) -> None:
        with self._lock:
            tids = list(self._threads.get(scope.key, set()))
        for t in tids:
            self._drop_thread(scope, t)

    def _drop_thread(self, scope: Scope, tid: str) -> None:
        try:
            self.checkpointer.delete_thread(tid)
        except Exception:  # best effort: conversation rows are the source of truth for deletion
            log.warning("could not delete checkpoint thread %s", tid)
        with self._lock:
            self._threads.get(scope.key, set()).discard(tid)

    def history(self, scope: Scope, user_id: str, conversation_id: str) -> list[dict]:
        """Checkpoint trail of a conversation (newest first): node path, route and trace per turn. For debugging/audit."""
        cfg = {"configurable": {"thread_id": self.thread_id(scope, user_id, conversation_id)}}
        out = []
        for snap in self.graph.get_state_history(cfg):
            v = snap.values
            if v.get("result"):
                out.append({"question": v.get("question"), "route": v.get("route"), "trace": v.get("trace"), "verification": v.get("verification"), "next": list(snap.next)})
        return out

    # ------------------------------------------------------------------ run
    def _prepare(self, scope, req, principal, conversation_id, history, summary):
        rid = uuid.uuid4().hex
        s = self.k.settings
        ctx = RunCtx(scope=scope, principal=principal, req=req, opts=resolve(s, req.retrieval), history=(history or [])[-s.memory_turns:], summary=summary)
        with self._lock:
            self._ctx[rid] = ctx
            tid = self.thread_id(scope, getattr(principal, "user_id", "anon"), conversation_id)
            self._threads.setdefault(scope.key, set()).add(tid)
        init = {"rid": rid, "question": req.question.strip(), "query": req.question.strip(), "attempt": 0, "trace": [], "evidence": [], "followups": []}
        return rid, ctx, init, {"configurable": {"thread_id": tid}}

    def _finish(self, rid: str, ctx: RunCtx, result: dict) -> AskResponse:
        result["usage"] = ctx.usage.as_dict() if ctx.usage else {}
        result["latency_ms"] = round((time.perf_counter() - ctx.t0) * 1000, 1)
        return AskResponse(**result)

    def ask(self, scope: Scope, req: AskRequest, principal=None, conversation_id: str = "default", history: Optional[list[dict]] = None,
            summary: Optional[str] = None) -> AskResponse:
        self.k.stats.questions += 1
        rid, ctx, init, cfg = self._prepare(scope, req, principal, conversation_id, history, summary)
        ctx.usage = Usage()
        try:
            state = self.graph.invoke(init, cfg)
            return self._finish(rid, ctx, dict(state["result"]))
        finally:
            with self._lock:
                self._ctx.pop(rid, None)

    def ask_stream(self, scope: Scope, req: AskRequest, principal=None, conversation_id: str = "default", history: Optional[list[dict]] = None,
                   summary: Optional[str] = None) -> Iterator[dict]:
        """Yields {"type": "step"|"token"|"final"|"error", ...}. Steps are real graph progress; the answer text is then streamed in
        small pieces (provider-side token streaming is not implemented)."""
        self.k.stats.questions += 1
        rid, ctx, init, cfg = self._prepare(scope, req, principal, conversation_id, history, summary)
        final: Optional[dict] = None
        ctx.usage = Usage()
        try:
            for upd in self.graph.stream(init, cfg, stream_mode="updates"):
                for node, delta in upd.items():
                    if delta and delta.get("trace"):
                        yield {"type": "step", "node": node, "detail": delta["trace"][-1]}
                    if delta and delta.get("result"):
                        final = dict(delta["result"])
            resp = self._finish(rid, ctx, final)
            text = resp.answer
            for i in range(0, len(text), 40):
                yield {"type": "token", "text": text[i:i + 40]}
            yield {"type": "final", "response": resp.model_dump()}
        finally:
            with self._lock:
                self._ctx.pop(rid, None)
