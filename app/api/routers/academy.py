from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...academy import service as ac
from ...db import AcademyProject
from ..deps import Ctx, require

router = APIRouter(prefix="/academy", tags=["academy"])
Learn = Depends(require("learn"))


def _lesson(lid: str) -> dict:
    x = ac.lessons().get(lid)
    if not x:
        raise HTTPException(404, "Lesson not found")
    return x


@router.get("/catalog", summary="Categories with their lessons, and the beginner-to-production roadmap")
def catalog(ctx: Ctx = Learn):
    return ac.catalog()


@router.get("/lessons/{lesson_id}", summary="One lesson in English, Hindi and Hinglish (quiz answers and exercise solutions are not included)")
def lesson(lesson_id: str, ctx: Ctx = Learn):
    return ac.public_lesson(_lesson(lesson_id))


@router.get("/glossary", summary="Technical terms with English, Hindi and Hinglish definitions")
def glossary(ctx: Ctx = Learn):
    return ac.glossary()


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100), ctx: Ctx = Learn):
    return ac.search(q)


@router.get("/progress", summary="Your progress: lessons, categories, quiz scores, streak, weak topics, bookmarks, where to continue")
def progress(ctx: Ctx = Learn):
    with ctx.svc.db.session() as s:
        return {**ac.overview(s, ctx.principal.user_id), "projects": ac.project_progress(s, ctx.principal.user_id)}


class ProgressBody(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(in_progress|done)$")
    step: Optional[int] = Field(default=None, ge=0, le=50)
    bookmarked: Optional[bool] = None


@router.put("/progress/{lesson_id}")
def put_progress(lesson_id: str, body: ProgressBody, ctx: Ctx = Learn):
    _lesson(lesson_id)
    with ctx.svc.db.session() as s:
        r = ac.set_progress(s, ctx.principal.user_id, lesson_id, body.status, body.step, body.bookmarked)
        return {"lesson": lesson_id, "status": r.status, "step": r.step, "bookmarked": r.bookmarked}


class QuizBody(BaseModel):
    answers: dict[str, int] = Field(min_length=1, max_length=40, description="question id -> index of the chosen option")


@router.post("/quiz/submit", summary="Grade answers on the server; returns the right answer and why every option is right or wrong")
def quiz_submit(body: QuizBody, ctx: Ctx = Learn):
    with ctx.svc.db.session() as s:
        out = ac.grade(s, ctx.principal.user_id, body.answers)
    if not out["results"]:
        raise HTTPException(422, "No known question ids")
    return out


@router.get("/daily", summary="Five practice questions for today (weak topics first); answers are only revealed after submitting")
def daily(ctx: Ctx = Learn):
    with ctx.svc.db.session() as s:
        return {"questions": ac.daily_questions(s, ctx.principal.user_id)}


@router.get("/interview", summary="Interview questions with concise model answers, filterable by category")
def interview(category: Optional[str] = None, ctx: Ctx = Learn):
    bank = ac.interview_bank()
    return [b for b in bank if not category or b["category"] == category]


@router.get("/projects", summary="Guided end-to-end projects")
def projects(ctx: Ctx = Learn):
    with ctx.svc.db.session() as s:
        prog = ac.project_progress(s, ctx.principal.user_id)
    return [{"id": p["id"], "title": p["title"], "summary": p["summary"], "level": p["level"], "hours": p["hours"], "stack": p["stack"], "steps": len(p["steps"]), "done": len(prog.get(p["id"], []))} for p in ac.projects().values()]


@router.get("/projects/{project_id}")
def project(project_id: str, ctx: Ctx = Learn):
    p = ac.projects().get(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    with ctx.svc.db.session() as s:
        done = ac.project_progress(s, ctx.principal.user_id).get(project_id, [])
    return {**p, "done_steps": done}


class ProjectBody(BaseModel):
    done_steps: list[int] = Field(max_length=60)


@router.put("/projects/{project_id}/progress")
def project_progress(project_id: str, body: ProjectBody, ctx: Ctx = Learn):
    p = ac.projects().get(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    steps = sorted({i for i in body.done_steps if 0 <= i < len(p["steps"])})
    with ctx.svc.db.session() as s:
        row = s.scalar(select(AcademyProject).where(AcademyProject.user_id == ctx.principal.user_id, AcademyProject.project_id == project_id))
        if row is None:
            s.add(AcademyProject(user_id=ctx.principal.user_id, project_id=project_id, done_steps=steps))
        else:
            row.done_steps = steps
        ac.touch_activity(s, ctx.principal.user_id)
    return {"project": project_id, "done_steps": steps}
