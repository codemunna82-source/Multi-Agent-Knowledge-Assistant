"""Generated reports (PDF / DOCX / XLSX) with sources and timestamps. Files live under <data_dir>/tenants/<tenant>/reports/."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ...core import ProviderError
from ...db import Report
from ...reports import build as builders
from ...reports.render import MIME
from ...reports.service import ReportTooLarge, generate
from ..deps import Ctx, page_params, require

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportBody(BaseModel):
    kind: Literal["summary", "executive", "comparison", "research", "analytics", "exact_search"]
    format: Literal["pdf", "docx", "xlsx"] = "pdf"
    source_ids: Optional[list[str]] = Field(default=None, max_length=20, description="documents to include (default: all accessible, up to 20)")
    params: dict = Field(default_factory=dict, description="kind-specific: style/section (summary), mode (comparison: diff|contradictions), questions[] (research), term (exact_search), "
                                                           "sheet/date_column/value_column/queries[] (analytics)")
    title: Optional[str] = Field(default=None, max_length=200)


class ReportOut(BaseModel):
    id: str
    kind: str
    format: str
    title: str
    status: str
    size_bytes: Optional[int]
    created_at: str
    workspace: str
    owner_id: str
    download_url: str


def _out(r: Report) -> ReportOut:
    return ReportOut(id=r.id, kind=r.kind, format=r.format, title=r.title, status=r.status, size_bytes=r.size_bytes, created_at=r.created_at.isoformat(), workspace=r.workspace,
                     owner_id=r.user_id, download_url=f"/reports/{r.id}/download")


def _mine(s, ctx: Ctx, rid: str) -> Report:
    r = s.get(Report, rid)
    if not r or r.tenant_id != ctx.principal.tenant_id or (r.user_id != ctx.principal.user_id and ctx.principal.role != "admin"):
        raise HTTPException(404, "Report not found")  # other users' reports are indistinguishable from missing ones
    return r


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:60] or "report"


@router.post("", response_model=ReportOut, status_code=201, summary="Generate a report from your documents (synchronous; large documents can take a while)")
def create_report(body: ReportBody, ctx: Ctx = Depends(require("report", "ask"))):
    svc = ctx.svc
    try:
        row = generate(svc.knowledge, svc.assistant, ctx.principal, ctx.scope, body.kind, body.format, body.source_ids, body.params, body.title)
    except builders.ReportError as e:
        raise HTTPException(422, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ProviderError as e:
        raise HTTPException(502, f"Model/API error: {e}")
    except ReportTooLarge as e:
        raise HTTPException(413, str(e))
    out = _out(row)
    ctx.audit("report_create", out.id, detail={"kind": body.kind, "format": body.format, "bytes": row.size_bytes})
    return out


@router.get("", response_model=list[ReportOut], summary="Your reports (admins see the whole organisation)")
def list_reports(response: Response, kind: Optional[str] = None, page: tuple[int, int] = Depends(page_params), ctx: Ctx = Depends(require("report"))):
    limit, offset = page
    with ctx.svc.db.session() as s:
        cond = [Report.tenant_id == ctx.principal.tenant_id] + ([] if ctx.principal.role == "admin" else [Report.user_id == ctx.principal.user_id]) + ([Report.kind == kind] if kind else [])
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(Report).where(*cond)) or 0)
        return [_out(r) for r in s.scalars(select(Report).where(*cond).order_by(Report.created_at.desc()).limit(limit).offset(offset))]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        return _out(_mine(s, ctx, report_id))


@router.get("/{report_id}/download")
def download(report_id: str, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        r = _mine(s, ctx, report_id)
        path, fmt, title = Path(r.path or ""), r.format, r.title
    if not path.is_file():
        raise HTTPException(410, "The report file is no longer available (retention policy or storage cleanup)")
    ctx.audit("report_download", report_id)
    return FileResponse(path, media_type=MIME[fmt], filename=f"{_slug(title)}.{fmt}", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{report_id}")
def delete_report(report_id: str, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        r = _mine(s, ctx, report_id)
        path = Path(r.path) if r.path else None
        s.delete(r)
    if path:
        path.unlink(missing_ok=True)
    ctx.audit("report_delete", report_id)
    return {"deleted": report_id}
