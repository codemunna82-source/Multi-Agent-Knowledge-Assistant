"""Session-based conversational memory: a bounded window of recent turns + a rolling summary of older ones.
Messages stay in PostgreSQL (UI history); only the window and summary are handed to the agents."""
from __future__ import annotations

from sqlalchemy import func, select

from .core import ProviderError
from .core import stem, tokenize
from .db import Conversation, MemoryFact, Message, UserPref
from .security.pii import findings
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


# ----------------------------------------------------------------------------- user-controlled memory
MAX_FACTS = 50
FACT_CHARS = 300


class MemoryRefused(ValueError):
    """A note was not stored (sensitive content, empty, or the limit was reached); the message tells the user why."""


def get_prefs(db, user_id: str) -> UserPref:
    """Stored preferences, or the defaults (conversation memory on, long-term notes off) for users who never changed them. Read-only."""
    with db.session() as s:
        p = s.get(UserPref, user_id)
        if p is None:
            return UserPref(user_id=user_id, memory_enabled=True, long_term_memory=False, theme="system")
        s.expunge(p)
        return p


def set_prefs(db, user_id: str, **changes) -> UserPref:
    with db.session() as s:
        p = s.get(UserPref, user_id) or UserPref(user_id=user_id, memory_enabled=True, long_term_memory=False, theme="system")
        for k, v in changes.items():
            if v is not None:
                setattr(p, k, v)
        s.merge(p)
    return get_prefs(db, user_id)


def add_fact(db, tenant_id: str, user_id: str, text: str) -> MemoryFact:
    text = " ".join(text.split())
    if not text:
        raise MemoryRefused("Nothing to remember")
    if len(text) > FACT_CHARS:
        raise MemoryRefused(f"Notes are limited to {FACT_CHARS} characters")
    bad = findings(text)
    if bad:
        raise MemoryRefused("This looks like it contains " + ", ".join(bad) + "; sensitive data is not stored in memory. Rephrase without it.")
    with db.session() as s:
        n = s.scalar(select(func.count()).select_from(MemoryFact).where(MemoryFact.tenant_id == tenant_id, MemoryFact.user_id == user_id)) or 0
        if n >= MAX_FACTS:
            raise MemoryRefused(f"You already have {MAX_FACTS} notes; delete some first")
        f = MemoryFact(tenant_id=tenant_id, user_id=user_id, text=text)
        s.add(f)
        s.flush()
        s.expunge(f)
        return f


def recall(db, tenant_id: str, user_id: str, question: str, n: int = 3) -> list[MemoryFact]:
    """The saved notes that share content words with the question (best first). Only called when the user switched long-term memory on."""
    q = {stem(t) for t in tokenize(question) if len(t) > 2}
    if not q:
        return []
    with db.session() as s:
        facts = list(s.scalars(select(MemoryFact).where(MemoryFact.tenant_id == tenant_id, MemoryFact.user_id == user_id).order_by(MemoryFact.id.desc())))
        scored = sorted(((len(q & {stem(t) for t in tokenize(f.text)}), f.id, f) for f in facts), key=lambda x: (-x[0], -x[1]))
        out = [f for sc, _, f in scored if sc > 0][:n]
        for f in out:
            s.expunge(f)
        return out
