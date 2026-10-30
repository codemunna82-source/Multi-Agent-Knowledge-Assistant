"""User-controlled memory: preferences, opt-in long-term notes, and reset. Everything is scoped to the signed-in user inside their tenant."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from ...db import Conversation, MemoryFact, User
from ...memory import MemoryRefused, add_fact, get_prefs, set_prefs
from ..deps import Ctx, require

router = APIRouter(prefix="/memory", tags=["memory"])


class PrefsBody(BaseModel):
    memory_enabled: Optional[bool] = Field(default=None, description="False = every question is private: no history is read, nothing is stored")
    long_term_memory: Optional[bool] = Field(default=None, description="True = saved notes relevant to a question are given to the model as context (never as evidence)")


class PrefsOut(BaseModel):
    memory_enabled: bool
    long_term_memory: bool


class FactBody(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class FactOut(BaseModel):
    id: int
    text: str
    created_at: str


def _prefs_out(db, user_id: str) -> PrefsOut:
    p = get_prefs(db, user_id)
    return PrefsOut(memory_enabled=p.memory_enabled, long_term_memory=p.long_term_memory)


def _real_user(ctx: Ctx) -> None:
    with ctx.svc.db.session() as s:
        if s.get(User, ctx.principal.user_id) is None:
            raise HTTPException(409, "Memory settings need a signed-in user (authentication is disabled on this server)")


@router.get("/preferences", response_model=PrefsOut)
def get_preferences(ctx: Ctx = Depends(require("memory"))):
    return _prefs_out(ctx.svc.db, ctx.principal.user_id)


@router.put("/preferences", response_model=PrefsOut)
def put_preferences(body: PrefsBody, ctx: Ctx = Depends(require("memory"))):
    _real_user(ctx)
    set_prefs(ctx.svc.db, ctx.principal.user_id, memory_enabled=body.memory_enabled, long_term_memory=body.long_term_memory)
    ctx.audit("memory_preferences", None, detail=body.model_dump(exclude_none=True))
    return _prefs_out(ctx.svc.db, ctx.principal.user_id)


@router.get("/facts", response_model=list[FactOut])
def list_facts(response: Response, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), ctx: Ctx = Depends(require("memory"))):
    with ctx.svc.db.session() as s:
        cond = (MemoryFact.tenant_id == ctx.principal.tenant_id, MemoryFact.user_id == ctx.principal.user_id)
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(MemoryFact).where(*cond)) or 0)
        rows = s.scalars(select(MemoryFact).where(*cond).order_by(MemoryFact.id.desc()).limit(limit).offset(offset)).all()
        return [FactOut(id=f.id, text=f.text, created_at=f.created_at.isoformat()) for f in rows]


@router.post("/facts", response_model=FactOut, status_code=201)
def create_fact(body: FactBody, ctx: Ctx = Depends(require("memory"))):
    """Save a note you explicitly want remembered. Notes that look like secrets, card/ID numbers, e-mail addresses or phone numbers are refused."""
    _real_user(ctx)
    try:
        f = add_fact(ctx.svc.db, ctx.principal.tenant_id, ctx.principal.user_id, body.text)
    except MemoryRefused as e:
        ctx.audit("memory_fact_add", None, "denied", {"reason": str(e)[:120]})
        raise HTTPException(422, str(e))
    ctx.audit("memory_fact_add", str(f.id))
    return FactOut(id=f.id, text=f.text, created_at=f.created_at.isoformat())


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: int, ctx: Ctx = Depends(require("memory"))):
    with ctx.svc.db.session() as s:
        f = s.get(MemoryFact, fact_id)
        if not f or f.tenant_id != ctx.principal.tenant_id or f.user_id != ctx.principal.user_id:
            raise HTTPException(404, "Note not found")
        s.delete(f)
    ctx.audit("memory_fact_delete", str(fact_id))
    return {"deleted": fact_id}


@router.delete("", summary="Reset memory: delete all saved notes and the rolling summaries of your conversations (optionally the conversations too)")
def reset_memory(conversations: bool = Query(False, description="also delete all your conversations and their messages"), ctx: Ctx = Depends(require("memory"))):
    t, u = ctx.principal.tenant_id, ctx.principal.user_id
    with ctx.svc.db.session() as s:
        facts = s.execute(delete(MemoryFact).where(MemoryFact.tenant_id == t, MemoryFact.user_id == u)).rowcount
        convs = s.scalars(select(Conversation).where(Conversation.tenant_id == t, Conversation.user_id == u)).all()
        ids = [(c.id, c.workspace) for c in convs]
        for c in convs:
            if conversations:
                s.delete(c)
            else:
                c.summary, c.summary_upto = None, 0
    if conversations:
        from ...storage import Scope

        for cid, ws in ids:
            ctx.svc.assistant.forget(Scope(t, ws), cid, u)
    ctx.audit("memory_reset", None, detail={"facts": facts, "conversations_deleted": len(ids) if conversations else 0})
    return {"facts_deleted": facts, "conversations_deleted": len(ids) if conversations else 0, "summaries_cleared": 0 if conversations else len(ids)}
