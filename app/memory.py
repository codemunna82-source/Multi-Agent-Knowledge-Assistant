"""Session-based conversational memory: a bounded window of recent turns + a rolling summary of older ones.
Messages stay in PostgreSQL (UI history); only the window and summary are handed to the agents."""
from __future__ import annotations

from sqlalchemy import select

from .core import ProviderError
from .db import Conversation, Message
from .tools.summarise import extractive


def _turns(msgs: list[Message]) -> list[dict]:
    out, q = [], None
    for m in msgs:
        if m.role == "user":
            q = m.content
        elif m.role == "assistant" and q is not None:
            meta = m.meta or {}
            out.append({"question": q, "answer": m.content[:600], "route": meta.get("route"), "term": meta.get("term")})
            q = None
    return out


def load_memory(db, llm, conv_id: str, window_turns: int) -> tuple[list[dict], str | None]:
    with db.session() as s:
        conv = s.get(Conversation, conv_id)
        msgs = list(s.scalars(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)))
        keep = window_turns * 2
        older, recent = msgs[:-keep] if len(msgs) > keep else [], msgs[-keep:]
        if older and conv.summary_upto < len(older):
            new = _turns(older[conv.summary_upto:])
            text = (conv.summary or "") + "\n" + "\n".join(f"Q: {t['question'][:200]} A: {t['answer'][:200]}" for t in new)
            summary = None
            if llm.available:
                try:
                    summary = llm.complete("Summarise this conversation so far in at most 6 short bullet points. Keep names, IDs, numbers and the documents discussed.", text[-6000:])
                except ProviderError:
                    summary = None
            conv.summary = summary or extractive(text, 6) or text[-1500:]
            conv.summary_upto = len(older)
        return _turns(recent), conv.summary
