from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from ...core import ProviderError
from ...db import Conversation, Message
from ...memory import load_memory
from ...schemas import AskRequest, AskResponse, ConversationOut, MessageOut
from ...security.audit import digest
from ..deps import Ctx, require

router = APIRouter(tags=["chat"])


def _conv(db_s, ctx: Ctx, conv_id: str) -> Conversation:
    c = db_s.get(Conversation, conv_id)
    if not c or c.tenant_id != ctx.principal.tenant_id or c.user_id != ctx.principal.user_id:
        raise HTTPException(404, "Conversation not found")  # other users' conversations are indistinguishable from missing ones
    return c


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, ctx: Ctx = Depends(require("ask", "ask"))):
    svc = ctx.svc
    with svc.db.session() as s:
        if body.conversation_id:
            conv = _conv(s, ctx, body.conversation_id)
            if conv.workspace != ctx.scope.workspace:
                raise HTTPException(409, "Conversation belongs to a different workspace")
        else:
            conv = s.scalar(select(Conversation).where(Conversation.tenant_id == ctx.principal.tenant_id, Conversation.user_id == ctx.principal.user_id,
                                                       Conversation.workspace == ctx.scope.workspace).order_by(Conversation.updated_at.desc()).limit(1))
            if not conv:
                conv = Conversation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, title=body.question[:60])
                s.add(conv)
                s.flush()
        conv_id = conv.id
    history, summary = load_memory(svc.db, svc.knowledge.llm, conv_id, svc.settings.memory_turns)
    try:
        resp = svc.assistant.ask(ctx.scope, body, ctx.principal, conversation_id=conv_id, history=history, summary=summary)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ProviderError as e:
        ctx.audit("ask", conv_id, "failed", {"error": "provider"})
        raise HTTPException(502, f"Model/API error: {e}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Upstream error: {e}")
    resp.request_id, resp.conversation_id = request.state.request_id, conv_id
    with svc.db.session() as s:
        s.add(Message(conversation_id=conv_id, role="user", content=body.question))
        s.add(Message(conversation_id=conv_id, role="assistant", content=resp.answer,
                      meta={"route": resp.route, "confidence": resp.confidence, "verified": resp.verified, "term": resp.details.get("term"),
                            "citations": [c.model_dump() for c in resp.citations], "limitations": resp.limitations, "followups": resp.followups,
                            "usage": resp.usage, "latency_ms": resp.latency_ms}))
        s.get(Conversation, conv_id).updated_at = __import__("app.db", fromlist=["now"]).now()
    ctx.audit("ask", conv_id, detail={"route": resp.route, "verified": resp.verified, "question": digest(body.question)})
    return resp


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(ctx: Ctx = Depends(require("ask")), limit: int = Query(50, le=200)):
    with ctx.svc.db.session() as s:
        rows = s.scalars(select(Conversation).where(Conversation.tenant_id == ctx.principal.tenant_id, Conversation.user_id == ctx.principal.user_id,
                                                    Conversation.workspace == ctx.scope.workspace).order_by(Conversation.updated_at.desc()).limit(limit)).all()
        return [ConversationOut(id=c.id, workspace=c.workspace, title=c.title, updated_at=c.updated_at.isoformat()) for c in rows]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def new_conversation(ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        c = Conversation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace)
        s.add(c)
        s.flush()
        return ConversationOut(id=c.id, workspace=c.workspace, title=c.title, updated_at=c.updated_at.isoformat())


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


@router.post("/ask/stream")
def ask_stream(body: AskRequest, request: Request, ctx: Ctx = Depends(require("ask", "ask"))):
    """Server-Sent Events: `step` (real graph progress), `token` (answer text pieces), `final` (full response incl. citations), `error`."""
    import json

    from fastapi.responses import StreamingResponse

    svc = ctx.svc
    with svc.db.session() as s:
        if body.conversation_id:
            conv = _conv(s, ctx, body.conversation_id)
        else:
            conv = Conversation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, title=body.question[:60])
            s.add(conv)
            s.flush()
        conv_id = conv.id
    history, summary = load_memory(svc.db, svc.knowledge.llm, conv_id, svc.settings.memory_turns)
    rid = request.state.request_id

    def gen():
        final = None
        try:
            for ev in svc.assistant.ask_stream(ctx.scope, body, ctx.principal, conversation_id=conv_id, history=history, summary=summary):
                if ev["type"] == "final":
                    ev["response"]["request_id"], ev["response"]["conversation_id"] = rid, conv_id
                    final = ev["response"]
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except KeyError as e:
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'detail': str(e.args[0])})}\n\n"
        except (ProviderError, httpx.HTTPError) as e:
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'detail': f'Model/API error: {e}'})}\n\n"
        if final:
            with svc.db.session() as s:
                s.add(Message(conversation_id=conv_id, role="user", content=body.question))
                s.add(Message(conversation_id=conv_id, role="assistant", content=final["answer"],
                              meta={"route": final["route"], "confidence": final["confidence"], "verified": final["verified"], "term": final["details"].get("term"),
                                    "citations": final["citations"], "limitations": final["limitations"], "followups": final["followups"], "usage": final["usage"]}))
            ctx.audit("ask", conv_id, detail={"route": final["route"], "verified": final["verified"], "question": digest(body.question), "stream": True})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations/{conv_id}/trace")
def conversation_trace(conv_id: str, ctx: Ctx = Depends(require("ask"))):
    """Checkpoint trail of the agent graph for this conversation (route, per-node trace, verification) - newest first."""
    with ctx.svc.db.session() as s:
        _conv(s, ctx, conv_id)
    return ctx.svc.assistant.history(ctx.scope, ctx.principal.user_id, conv_id)
