"""Answer feedback (thumbs up/down). Thumbs-down with an expected answer can be exported as an evaluation dataset, closing the loop from real use to regression tests."""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ...db import Feedback
from ...security.pii import redact
from ...tenant import redact_stored_messages
from ..deps import Ctx, page_params, require

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    rating: Literal[1, -1]
    route: Optional[str] = Field(default=None, max_length=32)
    question: Optional[str] = Field(default=None, max_length=2000, description="sent only when the user agrees (always needed to turn a thumbs-down into a test case)")
    answer: Optional[str] = Field(default=None, max_length=6000)
    comment: Optional[str] = Field(default=None, max_length=500)
    expected: Optional[str] = Field(default=None, max_length=1000, description="a phrase the correct answer must contain")
    sources: list[dict] = Field(default_factory=list, max_length=10, description='[{"source": "file.pdf", "location": "page 3"}] the answer cited, or should have cited')


class FeedbackOut(BaseModel):
    id: str
    rating: int
    route: Optional[str]
    question: Optional[str]
    comment: Optional[str]
    expected: Optional[str]
    created_at: str


def _out(f: Feedback) -> FeedbackOut:
    return FeedbackOut(id=f.id, rating=f.rating, route=f.route, question=f.question, comment=f.comment, expected=f.expected, created_at=f.created_at.isoformat())


@router.post("", response_model=FeedbackOut, status_code=201)
def add(body: FeedbackBody, ctx: Ctx = Depends(require("ask"))):
    mask = redact_stored_messages(ctx.svc.db, ctx.principal.tenant_id)
    t = (lambda x: redact(x) if (mask and x) else x)  # noqa: E731
    srcs = [{"source": str(s.get("source", ""))[:300], "location": str(s.get("location", ""))[:100]} for s in body.sources if s.get("source")]
    with ctx.svc.db.session() as s:
        f = Feedback(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, rating=body.rating, route=body.route, question=t(body.question),
                     answer=t(body.answer), comment=t(body.comment), expected=t(body.expected), sources=srcs)
        s.add(f)
        s.flush()
        out = _out(f)
    ctx.audit("feedback", out.id, detail={"rating": body.rating, "route": body.route})
    return out


@router.get("", response_model=list[FeedbackOut], summary="Your feedback (admins: the whole organisation)")
def list_feedback(response: Response, rating: Optional[int] = Query(None, ge=-1, le=1), page: tuple[int, int] = Depends(page_params), ctx: Ctx = Depends(require("ask"))):
    limit, offset = page
    with ctx.svc.db.session() as s:
        cond = [Feedback.tenant_id == ctx.principal.tenant_id] + ([] if ctx.principal.role == "admin" else [Feedback.user_id == ctx.principal.user_id]) + ([Feedback.rating == rating] if rating else [])
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(Feedback).where(*cond)) or 0)
        return [_out(f) for f in s.scalars(select(Feedback).where(*cond).order_by(Feedback.created_at.desc()).limit(limit).offset(offset))]


@router.get("/summary", summary="Counts by route (organisation-wide for managers and admins)")
def summary(ctx: Ctx = Depends(require("evaluate"))):
    with ctx.svc.db.session() as s:
        rows = s.execute(select(Feedback.route, Feedback.rating, func.count()).where(Feedback.tenant_id == ctx.principal.tenant_id).group_by(Feedback.route, Feedback.rating)).all()
    by: dict = {}
    for route, rating, n in rows:
        d = by.setdefault(route or "unknown", {"up": 0, "down": 0})
        d["up" if rating > 0 else "down"] += n
    return {"by_route": by, "up": sum(v["up"] for v in by.values()), "down": sum(v["down"] for v in by.values())}


@router.get("/eval-dataset", summary="Thumbs-down feedback that has a question and an expected phrase, as an evaluation dataset for POST /eval/run")
def eval_dataset(ctx: Ctx = Depends(require("evaluate"))):
    with ctx.svc.db.session() as s:
        rows = s.scalars(select(Feedback).where(Feedback.tenant_id == ctx.principal.tenant_id, Feedback.rating < 0, Feedback.question.is_not(None), Feedback.workspace == ctx.scope.workspace)
                         .order_by(Feedback.created_at)).all()
    cases = []
    for f in rows:
        kws = [f.expected.strip()] if f.expected and f.expected.strip() else []
        rel = [{"source": x["source"], "contains": None} for x in (f.sources or [])[:3]]
        if not kws and not rel:
            continue  # nothing checkable: a bare thumbs-down cannot become a test
        cases.append({"id": "fb-" + f.id[:8], "question": f.question, "type": "semantic", "relevant": rel, "expected_keywords": kws})
    if not cases:
        raise HTTPException(404, "No usable thumbs-down feedback yet (it needs a question and an expected phrase or a source)")
    return {"name": f"feedback-{re.sub(r'[^A-Za-z0-9_-]', '', ctx.scope.workspace)}", "cases": cases}


@router.delete("/{feedback_id}")
def delete(feedback_id: str, ctx: Ctx = Depends(require("ask"))):
    with ctx.svc.db.session() as s:
        f = s.get(Feedback, feedback_id)
        if not f or f.tenant_id != ctx.principal.tenant_id or (f.user_id != ctx.principal.user_id and ctx.principal.role != "admin"):
            raise HTTPException(404, "Feedback not found")
        s.delete(f)
    return {"deleted": feedback_id}
