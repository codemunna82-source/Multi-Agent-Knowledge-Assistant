"""Learning lab API: see what each retrieval technique, graph step and LangChain building block does on your own documents."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core import format_loc
from ...learn import lab, lc
from ...learn.catalog import LESSONS
from ...rag import RetrievalOptions, resolve
from ...schemas import AskRequest
from ..deps import Ctx, require

router = APIRouter(prefix="/learn", tags=["learn"])


class LabBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    source_ids: Optional[list[str]] = Field(default=None, max_length=20)
    top_k: int = Field(default=5, ge=1, le=10)


class CompareBody(LabBody):
    presets: Optional[list[str]] = Field(default=None, max_length=12, description="names from GET /learn/lessons → presets (default: all)")


class GraphRunBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    source_ids: Optional[list[str]] = Field(default=None, max_length=20)
    retrieval: Optional[RetrievalOptions] = None


class LcBody(LabBody):
    term: Optional[str] = Field(default=None, max_length=200, description="literal term for the tool demo (default: guessed from the question)")


def _scope(ctx: Ctx, ids: Optional[list[str]]):
    metas = ctx.svc.knowledge.store(ctx.scope).list_sources(ctx.principal)
    if ids:
        by = {m["id"]: m for m in metas}
        missing = [i for i in ids if i not in by]
        if missing:
            raise HTTPException(404, "Unknown source id(s): " + ", ".join(missing))
        metas = [by[i] for i in ids]
    if not metas:
        raise HTTPException(404, "No documents in this workspace: upload some first")
    return [m["id"] for m in metas if not m.get("tabular")] or [m["id"] for m in metas]


DEMO_QUESTIONS = [
    {"q": "How many days of annual leave do full-time employees accrue?", "teaches": "a plain factual question - most settings agree"},
    {"q": "How much vacation time do staff get yearly?", "teaches": "paraphrase: the offline hash embedder misses it, a real embedder finds it (semantic vs keyword)"},
    {"q": "Anjali Rao", "teaches": "a name: keyword/BM25 shines, pure semantic is weaker"},
    {"q": "Within how many hours must a security incident be reported?", "teaches": "numbers and units across a PDF page"},
    {"q": "How is Anjali Rao related to Delta Systems?", "teaches": "entities in different passages: graph expansion"},
    {"q": "How many weeks of parental leave do partners get?", "teaches": "a fact inside a longer section: parent-child shows the section, compression keeps only the relevant sentences"},
    {"q": "What is the cost of the Pro subscription per month?", "teaches": "a table inside a DOCX"},
]


@router.post("/demo-corpus", summary="Load the built-in sample documents (PDF, DOCX, XLSX, CSV, MD, TXT, JSON) into the current workspace so the labs have something to compare")
def demo_corpus(ctx: Ctx = Depends(require("ingest"))):
    import tempfile
    from pathlib import Path

    from ...eval.sample import corpus
    from ...learn.demo_long import handbook_md

    k = ctx.svc.knowledge
    done = []
    with tempfile.TemporaryDirectory() as td:
        for name, data in {**corpus(), "company_handbook.md": handbook_md()}.items():
            p = Path(td) / name
            p.write_bytes(data)
            r = k.ingest_file(ctx.scope, p, name, owner_id=ctx.principal.user_id)
            done.append({"name": name, "status": r["status"]})
    ctx.audit("learn_demo_corpus", None, detail={"files": len(done)})
    return {"documents": done, "questions": DEMO_QUESTIONS}


@router.get("/lessons", summary="Concept catalog with the lab action that demonstrates each one")
def lessons(ctx: Ctx = Depends(require("ask"))):
    k = ctx.svc.knowledge
    return {"lessons": LESSONS, "presets": list(lab.PRESETS), "ablation": [n for n, _ in lab.ABLATION], "llm_available": k.llm.available, "embedder": k.embedder.name,
            "demo_questions": DEMO_QUESTIONS, "note": "Without a language model, multi-query, HyDE, LLM re-ranking and Self-RAG run their deterministic fallbacks; the lab says so per row."}


@router.post("/retrieval/compare", summary="The same question under different retrieval settings, side by side")
def compare(body: CompareBody, ctx: Ctx = Depends(require("ask", "ask"))):
    ids = _scope(ctx, body.source_ids)
    names = body.presets or list(lab.PRESETS)
    bad = [n for n in names if n not in lab.PRESETS]
    if bad:
        raise HTTPException(422, "Unknown preset(s): " + ", ".join(bad))
    k, a = ctx.svc.knowledge, ctx.svc.assistant
    base = resolve(k.settings, RetrievalOptions(top_k=body.top_k))
    st = k.store(ctx.scope)
    rows = [lab.run_one(a.pipeline, k, st, body.question, n, base, lab.PRESETS[n], ids, body.top_k) for n in names]
    ctx.audit("learn_compare", None, detail={"presets": len(rows)})
    return {"question": body.question, "rows": lab.with_deltas(rows, reference=0)}


@router.post("/retrieval/ablation", summary="Switch techniques on one by one and see what each addition changes")
def ablation(body: LabBody, ctx: Ctx = Depends(require("ask", "ask"))):
    ids = _scope(ctx, body.source_ids)
    k, a = ctx.svc.knowledge, ctx.svc.assistant
    base = resolve(k.settings, RetrievalOptions(top_k=body.top_k))
    st = k.store(ctx.scope)
    cumulative: dict = {}
    rows = []
    for name, add in lab.ABLATION:
        cumulative = {**cumulative, **add}
        rows.append(lab.run_one(a.pipeline, k, st, body.question, name, base, dict(cumulative), ids, body.top_k))
    ctx.audit("learn_ablation", None, detail={"steps": len(rows)})
    return {"question": body.question, "rows": lab.with_deltas(rows)}


@router.get("/graph", summary="The compiled LangGraph: nodes, edges (conditional ones flagged) and Mermaid source")
def graph(ctx: Ctx = Depends(require("ask"))):
    return ctx.svc.assistant.graph_info()


@router.post("/graph/run", summary="Run a question and watch every graph step: node, time, state keys written, checkpoints")
def graph_run(body: GraphRunBody, ctx: Ctx = Depends(require("ask", "ask"))):
    _scope(ctx, body.source_ids)
    req = AskRequest(question=body.question, source_ids=body.source_ids, retrieval=body.retrieval, incognito=True)
    out = ctx.svc.assistant.trace_run(ctx.scope, req, ctx.principal)
    ctx.audit("learn_graph_run", None, detail={"steps": len(out["steps"])})
    return out


class ChunkBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=32)
    settings: list[dict] = Field(default_factory=lambda: [{"size": 400, "overlap": 50}, {"size": 1000, "overlap": 150}, {"size": 1000, "overlap": 150, "structure": True}, {"size": 2500, "overlap": 300}], max_length=6, description="[{size, overlap, structure?}]")


@router.post("/chunking", summary="How different chunk sizes cut one of your documents (nothing is re-indexed)")
def chunking(body: ChunkBody, ctx: Ctx = Depends(require("ask", "ask"))):
    from ...ingestion.chunking import chunk_units

    st = ctx.svc.knowledge.store(ctx.scope)
    meta = st.get_source(body.source_id, ctx.principal)
    if not meta:
        raise HTTPException(404, "Source not found")
    units = [u for _, u in st.iter_units([body.source_id])][:3000]
    rows = []
    for cfg in body.settings:
        size, overlap = int(cfg.get("size", 1000)), int(cfg.get("overlap", 150))
        if not (100 <= size <= 8000 and 0 <= overlap < size // 2):
            raise HTTPException(422, "size must be 100-8000 and overlap below half of it")
        structure = bool(cfg.get("structure", False))
        chunks = chunk_units(units, size, overlap, structure=structure)
        lens = [len(c.text) for c in chunks]
        rows.append({"size": size, "overlap": overlap, "structure": structure, "chunks": len(chunks), "avg_chars": round(sum(lens) / len(lens)) if lens else 0, "min_chars": min(lens, default=0), "max_chars": max(lens, default=0),
                     "tiny_chunks": sum(1 for n in lens if n < size * 0.2), "locations": len({str(c.loc) for c in chunks}),
                     "samples": [{"location": format_loc(c.loc, getattr(c, "loc_end", None)), "chars": len(c.text), "text": " ".join(c.text.split())[:220]} for c in chunks[:3]]})
    ctx.audit("learn_chunking", None)
    return {"source": meta["name"], "units": len(units), "rows": rows,
            "reading": "Smaller chunks match precisely but lose context (parent-child retrieval recovers it); larger chunks keep context but dilute the match. Chunks never cross a page/sheet/section, so 'tiny' chunks are the ends of those units."}


@router.post("/langchain", summary="Real langchain_core objects on your documents: retriever, LCEL chain, tool schema, parser, history")
def langchain_lab(body: LcBody, ctx: Ctx = Depends(require("ask", "ask"))):
    ids = _scope(ctx, body.source_ids)
    k, a = ctx.svc.knowledge, ctx.svc.assistant
    opts = resolve(k.settings, RetrievalOptions(top_k=body.top_k))
    out = lc.run_demo(a.pipeline, k, k.store(ctx.scope), body.question, opts, ids, body.term)
    ctx.audit("learn_langchain", None)
    return out
