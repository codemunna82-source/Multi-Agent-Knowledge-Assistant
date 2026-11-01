from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ...academy import playground as pg
from ...academy import playground_graph as pgg
from ...academy import sandbox
from ...academy import service as ac
from ...core import IngestError, ProviderError
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


# ----------------------------------------------------------------------------- playgrounds (real backend components; honest when something is not configured)
PG = Depends(require("learn", "playground"))


@router.get("/playground/capabilities", summary="What the playgrounds can really do on this server (LLM, embedder, cross-encoder, code runner)")
def pg_capabilities(ctx: Ctx = Learn):
    caps = pg.capabilities(ctx.svc.knowledge)
    ok, why = sandbox.available(ctx.svc.settings)
    caps["code_runner"] = {"available": ok, "reason": why or None}
    return caps


class LlmBody(BaseModel):
    system: str = Field(default="You are a helpful assistant.", max_length=pg.MAX_SYSTEM)
    prompt: str = Field(min_length=1, max_length=pg.MAX_PROMPT)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=300, ge=1, le=pg.MAX_TOKENS)


def _provider_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ProviderError as e:
        raise HTTPException(502, f"Model/API error: {e}")


@router.post("/playground/llm", summary="Run the configured LLM with chosen sampling parameters; reports tokens and latency")
def pg_llm(body: LlmBody, ctx: Ctx = PG):
    out = _provider_call(pg.llm_run, ctx.svc.knowledge, body.system, body.prompt, body.temperature, body.max_tokens)
    ctx.audit("academy_playground", "llm", detail={"available": out["available"], "chars": len(body.prompt)})
    return out


@router.post("/playground/llm/stream", summary="Server-Sent Events: token events as the model produces them, then done with usage and time to first token")
async def pg_llm_stream(body: LlmBody, request: Request, ctx: Ctx = PG):
    import asyncio
    import json
    import threading

    from fastapi.responses import StreamingResponse

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()
    END = object()
    k = ctx.svc.knowledge

    def pump():
        try:
            for ev in pg.llm_stream(k, body.system, body.prompt, body.temperature, body.max_tokens):
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(q.put_nowait, ev)
        except ProviderError as e:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "error", "detail": f"Model/API error: {e}"})
        except Exception:  # noqa: BLE001
            loop.call_soon_threadsafe(q.put_nowait, {"type": "error", "detail": "Something went wrong while generating."})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, END)

    async def gen():
        loop.run_in_executor(None, pump)
        try:
            while True:
                ev = await q.get()
                if ev is END:
                    break
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            stop.set()                       # Stop button / closed tab: the provider stream is abandoned

    ctx.audit("academy_playground", "llm-stream", detail={"chars": len(body.prompt)})
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Variant(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    system: str = Field(default="", max_length=pg.MAX_SYSTEM)
    prompt: str = Field(min_length=1, max_length=pg.MAX_PROMPT)


class CompareBody(BaseModel):
    variants: list[Variant] = Field(min_length=2, max_length=3)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=250, ge=1, le=pg.MAX_TOKENS)


@router.post("/playground/prompts/compare", summary="Run 2-3 prompt variants side by side and compare the outputs")
def pg_compare(body: CompareBody, ctx: Ctx = PG):
    out = _provider_call(pg.compare_prompts, ctx.svc.knowledge, [v.model_dump() for v in body.variants], body.temperature, body.max_tokens)
    ctx.audit("academy_playground", "prompts", detail={"variants": len(body.variants)})
    return out


class EmbedBody(BaseModel):
    texts: list[str] = Field(min_length=2, max_length=10)

    @field_validator("texts")
    @classmethod
    def _each(cls, v):
        if any(not t.strip() or len(t) > 500 for t in v):
            raise ValueError("every text must be 1-500 characters")
        return v


@router.post("/playground/embeddings", summary="Embed 2-10 sentences with the configured embedder; vector size, similarity matrix and ranking")
def pg_embed(body: EmbedBody, ctx: Ctx = PG):
    out = _provider_call(pg.embeddings_compare, ctx.svc.knowledge, [t.strip() for t in body.texts])
    ctx.audit("academy_playground", "embeddings", detail={"texts": len(body.texts)})
    return out


@router.post("/playground/rag", summary="An ephemeral RAG pipeline on an uploaded PDF/TXT/CSV or pasted text; every stage is returned (nothing is stored)")
async def pg_rag(file: Optional[UploadFile] = File(default=None), text: Optional[str] = Form(default=None), question: str = Form(min_length=1, max_length=500),
                 chunk_size: int = Form(default=500, ge=100, le=3000), chunk_overlap: int = Form(default=50, ge=0, le=500), top_k: int = Form(default=3, ge=1, le=8),
                 mode: Literal["vector", "keyword", "hybrid"] = Form(default="hybrid"), rerank: Literal["none", "lexical", "cross_encoder"] = Form(default="lexical"),
                 answer: bool = Form(default=True), ctx: Ctx = PG):
    import asyncio

    if (file is None) == (text is None):
        raise HTTPException(422, "Give either a file or pasted text")
    if chunk_overlap >= chunk_size:
        raise HTTPException(422, "overlap must be smaller than the chunk size")
    data = None
    if file is not None:
        data = await file.read(pg.RAG_LIMITS["file_bytes"] + 1)
    try:
        out = await asyncio.get_running_loop().run_in_executor(None, lambda: pg.rag_run(ctx.svc.knowledge, filename=file.filename if file else None, data=data, text=text, question=question, chunk_size=chunk_size,
                                                                                          overlap=chunk_overlap, top_k=top_k, mode=mode, rerank=rerank, answer=answer))
    except IngestError as e:
        raise HTTPException(422, str(e))
    except ProviderError as e:
        raise HTTPException(502, f"Model/API error: {e}")
    ctx.audit("academy_playground", "rag", detail={"chunks": out["chunks"]["count"], "mode": mode, "rerank": out["rerank"]["method"], "chars": out["extract"]["chars"]})
    return out


class LcBody(BaseModel):
    pattern: Literal["sequence", "parallel"] = "sequence"
    system: str = Field(default="You are a {role}.", max_length=500)
    template: str = Field(default="{question}", min_length=1, max_length=800)
    variables: dict[str, str] = Field(default_factory=dict, max_length=10)
    model: Literal["fake", "configured"] = "fake"
    fake_reply: str = Field(default="Paris, France, Europe", max_length=400)
    parser: Literal["str", "list", "json"] = "str"
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=200, ge=1, le=pg.MAX_TOKENS)

    @field_validator("variables")
    @classmethod
    def _vals(cls, v):
        if any(len(x) > 500 or len(k) > 30 for k, x in v.items()):
            raise ValueError("variable values are limited to 500 characters")
        return v


@router.post("/playground/langchain", summary="Run a real langchain_core pipeline (prompt | model | parser, optionally parallel); every component's input and output")
def pg_langchain(body: LcBody, ctx: Ctx = PG):
    try:
        out = _provider_call(pg.langchain_run, ctx.svc.knowledge, system=body.system, template=body.template, variables=body.variables, model=body.model, fake_reply=body.fake_reply,
                             parser=body.parser, pattern=body.pattern, temperature=body.temperature, max_tokens=body.max_tokens)
    except ValueError as e:
        raise HTTPException(422, str(e))
    ctx.audit("academy_playground", "langchain", detail={"model": body.model, "parser": body.parser})
    return out


@router.get("/playground/langgraph/presets", summary="Ready-made graphs: loop, conditional routing, human approval, supervisor")
def pg_presets(ctx: Ctx = Learn):
    return pgg.PRESETS


class GraphBody(BaseModel):
    spec: pgg.GraphSpec
    input: dict = Field(default_factory=dict, max_length=10)
    max_steps: int = Field(default=15, ge=2, le=25)


@router.post("/playground/langgraph/run", summary="Build and run a graph on the real LangGraph library; steps, state after each step, checkpoints. Pauses at interrupt_before nodes.")
def pg_graph_run(body: GraphBody, ctx: Ctx = PG):
    out = pgg.run_graph(ctx.principal.user_id, body.spec, body.input, body.max_steps)
    ctx.audit("academy_playground", "langgraph", detail={"nodes": len(body.spec.nodes), "status": out["status"], "steps": len(out["steps"])})
    return out


class ResumeBody(BaseModel):
    thread_id: str = Field(min_length=4, max_length=40)
    state_update: Optional[dict] = Field(default=None, max_length=10)
    max_steps: int = Field(default=15, ge=2, le=25)


@router.post("/playground/langgraph/resume", summary="Continue a paused graph, optionally after editing its state (human-in-the-loop)")
def pg_graph_resume(body: ResumeBody, ctx: Ctx = PG):
    out = pgg.resume_graph(ctx.principal.user_id, body.thread_id, body.state_update, body.max_steps)
    if out is None:
        raise HTTPException(404, "No paused run with that id (it may have finished or expired)")
    ctx.audit("academy_playground", "langgraph-resume", detail={"status": out["status"]})
    return out


class AgentBody(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    tools: list[str] = Field(default_factory=lambda: ["calculator", "search_documents", "list_documents"], max_length=6)
    max_steps: int = Field(default=4, ge=1, le=6)


@router.get("/playground/agent/tools", summary="The tools an agent may be given in the playground")
def pg_agent_tools(ctx: Ctx = Learn):
    return pgg.TOOL_DOCS


@router.post("/playground/agent/run", summary="Run an agent with an explicit tool allow-list; operational steps only (tool, input, result), never private reasoning")
def pg_agent(body: AgentBody, ctx: Ctx = PG):
    unknown = [t for t in body.tools if t not in pgg.TOOL_DOCS]
    if unknown:
        raise HTTPException(422, f"Unknown tool(s): {', '.join(unknown)}")
    out = _provider_call(pgg.run_agent, ctx.svc.knowledge, ctx.svc.assistant, ctx.scope, ctx.principal, body.task, body.tools, body.max_steps)
    ctx.audit("academy_playground", "agent", detail={"tools": body.tools, "steps": len(out["steps"])})
    return out
