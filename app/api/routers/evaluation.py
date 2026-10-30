from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...db import EvalRun
from ...eval.dataset import EvalDataset
from ...eval.report import html_report, markdown
from ...eval.runner import compare_strategies, run_eval
from ...rag import RetrievalOptions
from ...storage import Scope
from ..deps import Ctx, require

router = APIRouter(prefix="/eval", tags=["evaluation"])
STRATEGIES = {
    "semantic": RetrievalOptions(mode="semantic", reranker="none", compression=False, parent_child=False, corrective=False),
    "keyword (BM25)": RetrievalOptions(mode="keyword", reranker="none", compression=False, parent_child=False, corrective=False),
    "hybrid": RetrievalOptions(mode="hybrid", reranker="none", compression=False, parent_child=False, corrective=False),
    "hybrid + rerank + parent-child + corrective": RetrievalOptions(mode="hybrid", reranker="lexical", compression=True, parent_child=True, corrective=True),
}


class EvalRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    sample: bool = Field(default=False, description="Evaluate the built-in synthetic corpus in a throw-away workspace instead of your own documents")
    dataset: Optional[EvalDataset] = Field(default=None, description="Your questions + gold passages (required unless sample=true); evaluated against the current workspace")
    retrieval: Optional[RetrievalOptions] = None
    compare_strategies: bool = False
    use_llm_judge: bool = True


def _store(ctx: Ctx, rep: dict, name: str) -> str:
    with ctx.svc.db.session() as s:
        row = EvalRun(tenant_id=ctx.principal.tenant_id, name=name or rep["name"], config=rep["config"], metrics=rep["metrics"], report=rep)
        s.add(row)
        s.flush()
        return row.id


@router.post("/run")
def run(body: EvalRequest, ctx: Ctx = Depends(require("evaluate"))):
    """Runs synchronously (a few seconds for the sample; up to 500 questions otherwise). Results are stored per tenant."""
    a, k = ctx.svc.assistant, ctx.svc.knowledge
    if not body.sample and not body.dataset:
        raise HTTPException(422, "Provide `dataset` or set sample=true")
    if body.sample:
        from ...eval.sample import corpus, dataset

        scope = Scope(ctx.principal.tenant_id, f"eval-{Path(tempfile.mktemp()).name[-8:]}")
        ds = dataset()
        try:
            with tempfile.TemporaryDirectory() as td:
                for fname, data in corpus().items():
                    p = Path(td) / fname
                    p.write_bytes(data)
                    r = k.ingest_file(scope, p, fname, owner_id=ctx.principal.user_id)
                    if r["status"] != "ready":
                        raise HTTPException(500, f"Sample ingestion failed for {fname}: {r['error']}")
                rep = run_eval(a, scope, ctx.principal, ds, body.retrieval, None, body.use_llm_judge, body.name)
                if body.compare_strategies:
                    rep["comparison"] = compare_strategies(a, scope, ctx.principal, ds, STRATEGIES)["comparison"]
        finally:  # the throw-away workspace is erased completely (documents, vectors, checkpoints)
            st = k.store(scope)
            for m in st.list_sources():
                k.backend.delete(st, m["id"])
            st.clear()
            k.registry.delete_scope(scope.tenant, scope.workspace)
            import shutil

            shutil.rmtree(st.root, ignore_errors=True)
            a.forget_workspace(scope)
    else:
        scope = ctx.scope
        rep = run_eval(a, scope, ctx.principal, body.dataset, body.retrieval, None, body.use_llm_judge, body.name)
        if body.compare_strategies:
            rep["comparison"] = compare_strategies(a, scope, ctx.principal, body.dataset, STRATEGIES)["comparison"]
    rid = _store(ctx, rep, body.name)
    ctx.audit("eval_run", rid, detail={"cases": rep["metrics"]["cases"], "sample": body.sample})
    return {"id": rid, **rep}


@router.get("/runs")
def runs(response: Response, ctx: Ctx = Depends(require("evaluate")), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    from sqlalchemy import func

    with ctx.svc.db.session() as s:
        base = select(EvalRun).where(EvalRun.tenant_id == ctx.principal.tenant_id)
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(base.subquery())))
        rows = s.scalars(base.order_by(EvalRun.created_at.desc()).limit(limit).offset(offset)).all()
        return [{"id": r.id, "name": r.name, "created_at": r.created_at.isoformat(), "embedder": r.config.get("embedder"), "llm": r.config.get("llm"), "cases": r.metrics.get("cases"),
                 "recall@5": r.metrics.get("retrieval", {}).get("recall@5"), "mrr": r.metrics.get("retrieval", {}).get("mrr"),
                 "latency_p50": r.metrics.get("latency_ms", {}).get("p50"), "cost_per_query": r.metrics.get("cost_usd", {}).get("per_query")} for r in rows]


def _get(ctx: Ctx, run_id: str) -> dict:
    with ctx.svc.db.session() as s:
        r = s.get(EvalRun, run_id)
        if not r or r.tenant_id != ctx.principal.tenant_id:
            raise HTTPException(404, "Evaluation run not found")
        return r.report


@router.get("/runs/{run_id}")
def get_run(run_id: str, ctx: Ctx = Depends(require("evaluate"))):
    return {"id": run_id, **_get(ctx, run_id)}


@router.get("/runs/{run_id}/report.html", response_class=HTMLResponse)
def report_html(run_id: str, ctx: Ctx = Depends(require("evaluate"))):
    return HTMLResponse(html_report(_get(ctx, run_id)), headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def report_md(run_id: str, ctx: Ctx = Depends(require("evaluate"))):
    return PlainTextResponse(markdown(_get(ctx, run_id)))
