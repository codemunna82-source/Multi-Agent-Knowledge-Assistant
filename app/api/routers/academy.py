from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...academy import sandbox
from ...academy import service as ac
from ...db import AcademyExercise, AcademyProject
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


# ----------------------------------------------------------------------------- code runner (sandboxed)
@router.get("/code/status", summary="Whether code can be executed on this server, and what is enforced")
def code_status(ctx: Ctx = Learn):
    ok, why = sandbox.available(ctx.svc.settings)
    s = ctx.svc.settings
    return {"available": ok, "reason": why or None, "languages": list(sandbox.LANGS) if ok else [], "timeout_s": s.sandbox_timeout_s, "memory_mb": s.sandbox_memory_mb, "network": False,
            "limits": {"code_bytes": sandbox.MAX_CODE_BYTES, "output_bytes": sandbox.MAX_OUTPUT_BYTES}, "setup": None if ok else sandbox.SETUP_HELP,
            "preinstalled": ["python standard library", "numpy", "pydantic", "langchain-core", "langgraph"]}


class RunBody(BaseModel):
    language: Literal["python", "javascript"] = "python"
    code: str = Field(min_length=1, max_length=sandbox.MAX_CODE_BYTES)
    lesson_id: Optional[str] = Field(default=None, max_length=64)
    task: Literal["scratch", "example", "exercise", "debug"] = "scratch"
    example: int = Field(default=0, ge=0, le=20)


@router.post("/code/run", summary="Run learner code in an isolated sandbox (no network, CPU/memory/time/output limits); exercises are graded on the output")
def code_run(body: RunBody, ctx: Ctx = Depends(require("learn", "code"))):
    expected: Optional[str] = None
    lesson_id = body.lesson_id
    if body.task != "scratch":
        x = _lesson(lesson_id or "")
        if body.task == "example":
            codes = x["code"]
            if body.example >= len(codes) or not codes[body.example].get("runnable"):
                raise HTTPException(422, "That example is not runnable")
            expected = codes[body.example].get("expected_output")
        else:
            task = x.get(body.task)
            if not task:
                raise HTTPException(404, f"This lesson has no {body.task}")
            expected = task["expected_output"]
    try:
        r = sandbox.run(ctx.svc.settings, body.language, body.code)
    except sandbox.Busy as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "5"})
    except ValueError as e:
        raise HTTPException(422, str(e))
    passed = None
    if expected is not None and r.unavailable is None:
        passed = bool(r.ok and r.stdout.strip() == expected.strip())
        if body.task in ("exercise", "debug"):
            with ctx.svc.db.session() as s:
                ac.record_exercise(s, ctx.principal.user_id, lesson_id, body.task, passed)
    ctx.audit("academy_code_run", lesson_id, "denied" if r.unavailable else "success", {"language": body.language, "task": body.task, "bytes": len(body.code), "exit": r.exit_code, "ms": r.ms, "timed_out": r.timed_out})
    return {"ok": r.ok, "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.exit_code, "ms": r.ms, "timed_out": r.timed_out, "truncated": r.truncated, "unavailable": r.unavailable,
            "notes": r.notes, "error_help": sandbox.explain_error(r.stderr) if r.stderr else None, "passed": passed, "expected": expected if body.task == "example" else None}


@router.get("/lessons/{lesson_id}/solution/{kind}", summary="The reference solution of an exercise or debug task, available after at least one attempt")
def solution(lesson_id: str, kind: Literal["exercise", "debug"], ctx: Ctx = Learn):
    x = _lesson(lesson_id)
    task = x.get(kind)
    if not task:
        raise HTTPException(404, f"This lesson has no {kind}")
    with ctx.svc.db.session() as s:
        row = s.scalar(select(AcademyExercise).where(AcademyExercise.user_id == ctx.principal.user_id, AcademyExercise.lesson_id == lesson_id, AcademyExercise.kind == kind))
        tried = bool(row and row.attempts >= 1)
    if not tried:
        raise HTTPException(403, "Try the task at least once first - then the solution is unlocked.")
    return {"solution": task["solution"], "expected_output": task["expected_output"]}
