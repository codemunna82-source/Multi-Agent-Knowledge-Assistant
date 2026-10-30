from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select

from ...core import ProviderError
from ...db import Conversation, Message
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
    try:
        resp = svc.assistant.ask(ctx.scope, body, ctx.principal, conversation_id=conv_id)
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
                      meta={"route": resp.route, "confidence": resp.confidence, "verified": resp.verified,
                            "citations": [c.model_dump() for c in resp.citations], "limitations": resp.limitations}))
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
