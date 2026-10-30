"""Data-analyst API over uploaded CSV/Excel sources: profile, anomalies, trends, read-only SQL, natural-language questions and charts."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ...agents.data_answers import format_data_answer
from ...analytics import charts, insights, sqlbox
from ...analytics.nlsql import answer_with_sql
from ...tools import tabular as tab
from ..deps import Ctx, require

router = APIRouter(prefix="/analytics", tags=["analytics"])


class SqlBody(BaseModel):
    sql: str = Field(min_length=1, max_length=4000)
    source_ids: Optional[list[str]] = Field(default=None, max_length=20)
    max_rows: int = Field(default=200, ge=1, le=2000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    source_ids: Optional[list[str]] = Field(default=None, max_length=20)


class ChartBody(BaseModel):
    type: Literal["bar", "line"]
    title: str = Field(default="", max_length=200)
    x_label: str = Field(default="", max_length=100)
    y_label: str = Field(default="", max_length=100)
    labels: list[str] = Field(max_length=60)
    series: list[dict] = Field(min_length=1, max_length=6)


def _tables(ctx: Ctx, source_ids: list[str] | None = None) -> list[tab.Table]:
    k = ctx.svc.knowledge
    metas = [m for m in ctx.svc.knowledge.store(ctx.scope).list_sources(ctx.principal) if m.get("tabular") and (not source_ids or m["id"] in source_ids)]
    if not metas:
        raise HTTPException(404, "No CSV/Excel sources available")
    return tab.load_tables(k.store(ctx.scope), metas)


def _one(ctx: Ctx, source_id: str, sheet: str | None) -> tab.Table:
    ts = [t for t in _tables(ctx, [source_id]) if sheet is None or t.sheet == sheet]
    if not ts:
        raise HTTPException(404, "Source or sheet not found")
    return ts[0]


def _fail(e: Exception):
    raise HTTPException(422, str(e))


@router.get("/tables", summary="Tabular sources with their sheets and the SQL schema that /analytics/sql accepts")
def tables(ctx: Ctx = Depends(require("analytics"))):
    ts = _tables(ctx)
    sb = sqlbox.build(ts)
    try:
        return {"tables": sb.describe(), "limits": {"statement": "single SELECT/WITH", "timeout_s": 3, "max_rows": 2000}}
    finally:
        sb.conn.close()


@router.get("/profile", summary="Column types, missing values, statistics, duplicate rows")
def profile(source_id: str, sheet: Optional[str] = None, ctx: Ctx = Depends(require("analytics"))):
    return insights.profile(_one(ctx, source_id, sheet))


@router.get("/anomalies", summary="Outliers in a numeric column (IQR or z-score)")
def anomalies(source_id: str, column: str, sheet: Optional[str] = None, method: Literal["iqr", "zscore"] = "iqr", threshold: Optional[float] = Query(None, gt=0, le=100),
              ctx: Ctx = Depends(require("analytics"))):
    t = _one(ctx, source_id, sheet)
    try:
        out = insights.anomalies(t, column, method, threshold)
    except tab.PlanError as e:
        _fail(e)
    for r in out["rows"]:
        r["values"] = {k: insights._py(v) for k, v in t.df.loc[r["row"]].items()}
    return out


@router.get("/trend", summary="Value per month / quarter / year with change, year-over-year and direction")
def trend(source_id: str, date_column: str, sheet: Optional[str] = None, value_column: Optional[str] = None, freq: Literal["M", "Q", "Y"] = "M",
          agg: Literal["sum", "mean", "count", "min", "max", "median"] = "sum", ctx: Ctx = Depends(require("analytics"))):
    t = _one(ctx, source_id, sheet)
    try:
        out = insights.trend(t, date_column, value_column, freq, agg)
    except tab.PlanError as e:
        _fail(e)
    out["chart"] = charts.from_result({"kind": "trend", "trend": out})
    return out


@router.post("/sql", summary="Run one validated read-only SELECT over the uploaded tables (sandboxed)")
def run_sql(body: SqlBody, ctx: Ctx = Depends(require("analytics", "ask"))):
    ts = _tables(ctx, body.source_ids)
    sb = sqlbox.build(ts)
    try:
        try:
            res = sqlbox.run(sb, body.sql, max_rows=body.max_rows)
        except sqlbox.SqlError as e:
            ctx.audit("analytics_sql", None, "denied", {"error": str(e)[:200]})
            raise HTTPException(422, str(e))
        res["citations"] = [{"source_id": r["source_id"], "source": r["source"], "location": (f"sheet '{r['sheet']}', " if "sheet" in r else "") + f"row {r['row']}"} for r in sqlbox.cited_rows(sb, res)]
        ctx.audit("analytics_sql", None, detail={"rows": res["row_count"]})
        return res
    finally:
        sb.conn.close()


@router.post("/ask", summary="Natural-language question over the tables (fixed operations; a model-written validated SQL query when a model is configured)")
def ask(body: AskBody, ctx: Ctx = Depends(require("analytics", "ask"))):
    ts = _tables(ctx, body.source_ids)
    k = ctx.svc.knowledge
    try:
        out = tab.analyse(ts, body.question, k.llm)
    except tab.NotTabular:
        raise HTTPException(422, "The question does not refer to the table data")
    except tab.PlanError as e:
        if not k.llm.available:
            _fail(e)
        try:
            out = answer_with_sql(ts, body.question, k.llm)
        except tab.PlanError as e2:
            _fail(e2)
    ctx.audit("analytics_ask", None, detail={"op": out["plan"].get("op")})
    return format_data_answer(out)


@router.post("/chart", summary="Render a chart specification to PNG (for reports and downloads)", response_class=Response)
def chart_png(body: ChartBody, ctx: Ctx = Depends(require("analytics"))):
    try:
        spec = charts.spec(body.type, body.title, body.labels, [{"name": str(s.get("name", ""))[:60], "values": [v for v in s.get("values", [])][:60]} for s in body.series], body.x_label, body.y_label)
        png = charts.render_png(spec)
    except (ValueError, TypeError) as e:
        _fail(e)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
