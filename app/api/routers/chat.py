from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select

from ...core import ProviderError
from ...db import Conversation, Message, now
from ...memory import get_prefs, load_memory, recall
from ...schemas import AskRequest, AskResponse, ConversationOut, ConversationPatch, MessageOut
from ...security.audit import digest
from ...security.pii import redact
from ...tenant import redact_stored_messages
from ..deps import Ctx, require

router = APIRouter(tags=["chat"])


def _conv(db_s, ctx: Ctx, conv_id: str) -> Conversation:
    c = db_s.get(Conversation, conv_id)
    if not c or c.tenant_id != ctx.principal.tenant_id or c.user_id != ctx.principal.user_id:
        raise HTTPException(404, "Conversation not found")  # other users' conversations are indistinguishable from missing ones
    return c


class Turn:
    """Everything a question needs from the user's memory settings, resolved once: private questions read and store nothing."""

    def __init__(self, conv_id, history, summary, notes, private, thread, created=False):
        self.conv_id, self.history, self.summary, self.notes, self.private, self.thread = conv_id, history, summary, notes, private, thread
        self.created = created          # the conversation row was created by this very request


def begin_turn(ctx: Ctx, body: AskRequest, reuse_latest: bool = True) -> Turn:
    """Resolve conversation + memory for a question. `reuse_latest`: continue the user's latest conversation of the workspace (the /ask behaviour)."""
    svc = ctx.svc
    prefs = get_prefs(svc.db, ctx.principal.user_id)
    private = body.incognito or not prefs.memory_enabled
    conv_id, created = None, False
    with svc.db.session() as s:
        conv = None
        if body.conversation_id:
            conv = _conv(s, ctx, body.conversation_id)
            if conv.workspace != ctx.scope.workspace:
                raise HTTPException(409, "Conversation belongs to a different workspace")
            private = private or not conv.memory_enabled
        elif not private:
            if reuse_latest:
                conv = s.scalar(select(Conversation).where(Conversation.tenant_id == ctx.principal.tenant_id, Conversation.user_id == ctx.principal.user_id,
                                                           Conversation.workspace == ctx.scope.workspace, Conversation.memory_enabled.is_(True)).order_by(Conversation.updated_at.desc()).limit(1))
            if conv is None:
                conv = Conversation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, title=body.question[:60])
                s.add(conv)
                s.flush()
                created = True
        conv_id = conv.id if conv is not None and not private else None
    if private:
        return Turn(None, [], None, [], True, f"private-{uuid.uuid4().hex[:12]}")
    history, summary = load_memory(svc.db, svc.knowledge.llm, conv_id, svc.settings.memory_turns)
    if body.regenerate and history and history[-1].get("question") == body.question:
        history = history[:-1]      # the answer being replaced must not inform its own replacement
    notes = [f.text for f in recall(svc.db, ctx.principal.tenant_id, ctx.principal.user_id, body.question)] if prefs.long_term_memory else []
    return Turn(conv_id, history, summary, notes, False, conv_id, created)


def store_turn(ctx: Ctx, turn: Turn, question: str, answer: str, meta: dict, replace_last: bool = False) -> None:
    """Persist the exchange (unless private). Tenants with `redact_stored_messages` get e-mails, phone numbers, cards and secrets masked."""
    if turn.private:
        ctx.svc.assistant.forget(ctx.scope, turn.thread, ctx.principal.user_id)  # drop the throw-away checkpoint thread
        return
    if redact_stored_messages(ctx.svc.db, ctx.principal.tenant_id):
        question, answer = redact(question), redact(answer)
    with ctx.svc.db.session() as s:
        if replace_last:       # regenerate: only now, after the new answer exists, is the old exchange removed (and only if it really is this question)
            last = s.scalars(select(Message).where(Message.conversation_id == turn.conv_id).order_by(Message.id.desc()).limit(2)).all()
            if len(last) == 2 and last[0].role == "assistant" and last[1].role == "user" and last[1].content in (question, redact(question)):
                for m in last:
                    s.delete(m)
        s.add(Message(conversation_id=turn.conv_id, role="user", content=question))
        s.add(Message(conversation_id=turn.conv_id, role="assistant", content=answer, meta=meta))
        s.get(Conversation, turn.conv_id).updated_at = now()


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, ctx: Ctx = Depends(require("ask", "ask"))):
    svc = ctx.svc
    turn = begin_turn(ctx, body)
    try:
        resp = svc.assistant.ask(ctx.scope, body, ctx.principal, conversation_id=turn.thread, history=turn.history, summary=turn.summary, notes=turn.notes)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ProviderError as e:
        ctx.audit("ask", turn.conv_id, "failed", {"error": "provider"})
        raise HTTPException(502, f"Model/API error: {e}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Upstream error: {e}")
    resp.request_id, resp.conversation_id = request.state.request_id, turn.conv_id
    if turn.notes:
        resp.details["memory_notes_used"] = len(turn.notes)
    if turn.private:
        resp.details["private"] = True
    store_turn(ctx, turn, body.question, resp.answer,
               {"route": resp.route, "confidence": resp.confidence, "verified": resp.verified, "term": resp.details.get("term"), "citations": [c.model_dump() for c in resp.citations],
                "limitations": resp.limitations, "followups": resp.followups, "usage": resp.usage, "latency_ms": resp.latency_ms})
    ctx.audit("ask", turn.conv_id, detail={"route": resp.route, "verified": resp.verified, "question": digest(body.question), "private": turn.private})
    return resp


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(response: Response, ctx: Ctx = Depends(require("ask")), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    from sqlalchemy import func

    with ctx.svc.db.session() as s:
        base = select(Conversation).where(Conversation.tenant_id == ctx.principal.tenant_id, Conversation.user_id == ctx.principal.user_id, Conversation.workspace == ctx.scope.workspace)
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(base.subquery())))
        rows = s.scalars(base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)).all()
        return [ConversationOut(id=c.id, workspace=c.workspace, title=c.title, updated_at=c.updated_at.isoformat(), memory_enabled=c.memory_enabled) for c in rows]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def new_conversation(ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        c = Conversation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace)
        s.add(c)
        s.flush()
        return ConversationOut(id=c.id, workspace=c.workspace, title=c.title, updated_at=c.updated_at.isoformat(), memory_enabled=c.memory_enabled)


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
def patch_conversation(conv_id: str, body: ConversationPatch, ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        c = _conv(s, ctx, conv_id)
        if body.title is not None:
            c.title = body.title
        if body.memory_enabled is not None:
            c.memory_enabled = body.memory_enabled
        s.flush()
        out = ConversationOut(id=c.id, workspace=c.workspace, title=c.title, updated_at=c.updated_at.isoformat(), memory_enabled=c.memory_enabled)
    ctx.audit("update_conversation", conv_id, detail=body.model_dump(exclude_none=True))
    return out


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def messages(conv_id: str, ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        _conv(s, ctx, conv_id)
        return [MessageOut(id=m.id, role=m.role, content=m.content, meta=m.meta, created_at=m.created_at.isoformat())
                for m in s.scalars(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id))]


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        c = _conv(s, ctx, conv_id)
        s.delete(c)
    ctx.svc.assistant.forget(ctx.scope, conv_id)
    ctx.audit("delete_conversation", conv_id)
    return {"deleted": conv_id}


def _drop_if_empty(ctx: Ctx, turn: Turn) -> None:
    with ctx.svc.db.session() as s:
        c = s.get(Conversation, turn.conv_id)
        if c is not None and not s.scalar(select(Message.id).where(Message.conversation_id == turn.conv_id).limit(1)):
            s.delete(c)
    ctx.svc.assistant.forget(ctx.scope, turn.conv_id)


@router.post("/ask/stream")
async def ask_stream(body: AskRequest, request: Request, ctx: Ctx = Depends(require("ask", "ask"))):
    """Server-Sent Events. Same validation, authentication and rate limit as /ask. Events (JSON `data:` lines, `event:` = type):
    `status` (a stage started), `step` (a graph node finished), `draft` (real provider tokens, unverified), `draft_reset`, `final` (verified answer with citations),
    `done`, `error`. SSE comment lines (`: ping`) keep idle connections open. If the client disconnects (Stop), generation is cancelled and nothing is stored."""
    import asyncio
    import json
    import threading

    from fastapi.responses import StreamingResponse

    svc = ctx.svc
    turn = begin_turn(ctx, body, reuse_latest=False)
    rid = request.state.request_id
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    cancel = threading.Event()
    END = object()

    def pump():          # runs the (blocking) assistant generator in a worker thread; events cross to the event loop through a queue
        try:
            for ev in svc.assistant.ask_stream(ctx.scope, body, ctx.principal, conversation_id=turn.thread, history=turn.history, summary=turn.summary, notes=turn.notes, cancel=cancel):
                loop.call_soon_threadsafe(out.put_nowait, ev)
                if cancel.is_set():
                    break
        except KeyError as e:
            loop.call_soon_threadsafe(out.put_nowait, {"type": "error", "detail": str(e.args[0])})
        except (ProviderError, httpx.HTTPError) as e:
            loop.call_soon_threadsafe(out.put_nowait, {"type": "error", "detail": f"Model/API error: {e}"})
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("mka").exception("stream failed")
            loop.call_soon_threadsafe(out.put_nowait, {"type": "error", "detail": "Something went wrong while generating the answer."})
        finally:
            loop.call_soon_threadsafe(out.put_nowait, END)

    def sse(ev: dict) -> str:
        return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    async def gen():
        final = None
        failed = False
        loop.run_in_executor(None, pump)
        try:
            while True:
                ev = await out.get()
                if ev is END:
                    break
                if ev["type"] == "ping":
                    yield ": ping\n\n"
                    continue
                if ev["type"] == "final":
                    ev["response"]["request_id"], ev["response"]["conversation_id"] = rid, turn.conv_id
                    if turn.private:
                        ev["response"]["details"]["private"] = True
                    if turn.notes:
                        ev["response"]["details"]["memory_notes_used"] = len(turn.notes)
                    final = ev["response"]
                failed = failed or ev["type"] == "error"
                yield sse(ev)
        finally:
            cancel.set()           # client went away (Stop / closed tab / network loss) or the stream ended: stop any generation still running
            if turn.private and final is None:
                svc.assistant.forget(ctx.scope, turn.thread, ctx.principal.user_id)
            elif turn.created and (final is None or failed):
                _drop_if_empty(ctx, turn)       # a stopped / failed first question must not leave an empty conversation in the history list
        if final and not failed:
            store_turn(ctx, turn, body.question, final["answer"],
                       {"route": final["route"], "confidence": final["confidence"], "verified": final["verified"], "term": final["details"].get("term"),
                        "citations": final["citations"], "limitations": final["limitations"], "followups": final["followups"], "usage": final["usage"]}, replace_last=body.regenerate and not turn.private)
            ctx.audit("ask", turn.conv_id, detail={"route": final["route"], "verified": final["verified"], "question": digest(body.question), "stream": True, "private": turn.private,
                                                   "regenerate": body.regenerate})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/conversations/{conv_id}/trace")
def conversation_trace(conv_id: str, ctx: Ctx = Depends(require("ask"))):
    """Checkpoint trail of the agent graph for this conversation (route, per-node trace, verification) - newest first."""
    with ctx.svc.db.session() as s:
        _conv(s, ctx, conv_id)
    return ctx.svc.assistant.history(ctx.scope, ctx.principal.user_id, conv_id)
