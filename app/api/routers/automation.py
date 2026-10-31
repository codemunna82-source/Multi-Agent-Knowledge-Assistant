"""Automation API: saved searches + alerts, scheduled reports, connectors (folder / URL list / S3), annotations."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from ... import automation
from ...core import IngestError
from ...db import Alert, Annotation, Connector, ReportSchedule, SavedSearch
from ..deps import Ctx, page_params, require

router = APIRouter(tags=["automation"])


def _mine(row, ctx: Ctx, what: str):
    if not row or row.tenant_id != ctx.principal.tenant_id or (row.user_id != ctx.principal.user_id and ctx.principal.role != "admin"):
        raise HTTPException(404, f"{what} not found")
    return row


def _hook(ctx: Ctx, url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        automation.webhook_url_ok(ctx.svc.knowledge, url)
    except IngestError as e:
        raise HTTPException(422, f"Webhook URL rejected: {e}")
    return url


# ----------------------------------------------------------------------------- saved searches and alerts
class SearchBody(BaseModel):
    term: str = Field(min_length=2, max_length=200)
    whole_word: bool = True
    case_sensitive: bool = False
    webhook_url: Optional[str] = Field(default=None, max_length=500, description="POSTed a JSON event (ids, counts, locations - no document text) when a new document matches")


class SearchOut(BaseModel):
    id: str
    term: str
    whole_word: bool
    case_sensitive: bool
    webhook_url: Optional[str]
    workspace: str
    created_at: str


def _search_out(r: SavedSearch) -> SearchOut:
    return SearchOut(id=r.id, term=r.term, whole_word=r.whole_word, case_sensitive=r.case_sensitive, webhook_url=r.webhook_url, workspace=r.workspace, created_at=r.created_at.isoformat())


@router.post("/saved-searches", response_model=SearchOut, status_code=201, summary="Watch a name/phrase: every newly ingested document is searched and a match creates an alert")
def add_search(body: SearchBody, ctx: Ctx = Depends(require("search"))):
    with ctx.svc.db.session() as s:
        if (s.scalar(select(func.count()).select_from(SavedSearch).where(SavedSearch.user_id == ctx.principal.user_id)) or 0) >= 50:
            raise HTTPException(422, "You can watch at most 50 terms")
        r = SavedSearch(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, term=body.term.strip(), whole_word=body.whole_word,
                        case_sensitive=body.case_sensitive, webhook_url=_hook(ctx, body.webhook_url))
        s.add(r)
        s.flush()
        out = _search_out(r)
    ctx.audit("saved_search_add", out.id)
    return out


@router.get("/saved-searches", response_model=list[SearchOut])
def list_searches(ctx: Ctx = Depends(require("search"))):
    with ctx.svc.db.session() as s:
        return [_search_out(r) for r in s.scalars(select(SavedSearch).where(SavedSearch.tenant_id == ctx.principal.tenant_id, SavedSearch.user_id == ctx.principal.user_id,
                                                                            SavedSearch.workspace == ctx.scope.workspace).order_by(SavedSearch.created_at))]


@router.delete("/saved-searches/{sid}")
def delete_search(sid: str, ctx: Ctx = Depends(require("search"))):
    with ctx.svc.db.session() as s:
        s.delete(_mine(s.get(SavedSearch, sid), ctx, "Saved search"))
        s.execute(Alert.__table__.delete().where(Alert.saved_search_id == sid))
    return {"deleted": sid}


@router.get("/alerts", summary="Matches of your saved searches (newest first)")
def alerts(response: Response, unseen: bool = False, page: tuple[int, int] = Depends(page_params), ctx: Ctx = Depends(require("search"))):
    limit, offset = page
    with ctx.svc.db.session() as s:
        cond = [Alert.tenant_id == ctx.principal.tenant_id, Alert.user_id == ctx.principal.user_id] + ([Alert.seen.is_(False)] if unseen else [])
        response.headers["X-Total-Count"] = str(s.scalar(select(func.count()).select_from(Alert).where(*cond)) or 0)
        rows = s.scalars(select(Alert).where(*cond).order_by(Alert.created_at.desc()).limit(limit).offset(offset)).all()
        return [{"id": a.id, "term": a.term, "source_id": a.source_id, "source_name": a.source_name, "count": a.count, "locations": a.locations, "seen": a.seen, "created_at": a.created_at.isoformat()} for a in rows]


@router.post("/alerts/seen", summary="Mark all your alerts as seen")
def alerts_seen(ctx: Ctx = Depends(require("search"))):
    with ctx.svc.db.session() as s:
        n = s.execute(update(Alert).where(Alert.tenant_id == ctx.principal.tenant_id, Alert.user_id == ctx.principal.user_id, Alert.seen.is_(False)).values(seen=True)).rowcount
    return {"marked": n}


# ----------------------------------------------------------------------------- scheduled reports
class ScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["summary", "executive", "comparison", "research", "analytics", "exact_search"]
    format: Literal["pdf", "docx", "xlsx"] = "pdf"
    source_ids: Optional[list[str]] = Field(default=None, max_length=20)
    params: dict = Field(default_factory=dict)
    title: Optional[str] = Field(default=None, max_length=200)
    every_hours: int = Field(ge=1, le=24 * 31)
    webhook_url: Optional[str] = Field(default=None, max_length=500)


def _sched_out(r: ReportSchedule) -> dict:
    return {"id": r.id, "name": r.name, "spec": r.spec, "every_hours": r.every_hours, "webhook_url": r.webhook_url, "enabled": r.enabled, "workspace": r.workspace,
            "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None, "last_status": r.last_status, "created_at": r.created_at.isoformat()}


@router.post("/report-schedules", status_code=201, summary="Generate a report every N hours (run by the scheduler); optional webhook when it is ready")
def add_schedule(body: ScheduleBody, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        if (s.scalar(select(func.count()).select_from(ReportSchedule).where(ReportSchedule.user_id == ctx.principal.user_id)) or 0) >= 20:
            raise HTTPException(422, "You can have at most 20 schedules")
        r = ReportSchedule(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, name=body.name, every_hours=body.every_hours, webhook_url=_hook(ctx, body.webhook_url),
                           spec={"kind": body.kind, "format": body.format, "source_ids": body.source_ids, "params": body.params, "title": body.title})
        s.add(r)
        s.flush()
        out = _sched_out(r)
    ctx.audit("report_schedule_add", out["id"], detail={"every_hours": body.every_hours})
    return out


@router.get("/report-schedules")
def list_schedules(ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        cond = [ReportSchedule.tenant_id == ctx.principal.tenant_id] + ([] if ctx.principal.role == "admin" else [ReportSchedule.user_id == ctx.principal.user_id])
        return [_sched_out(r) for r in s.scalars(select(ReportSchedule).where(*cond).order_by(ReportSchedule.created_at))]


@router.post("/report-schedules/{sid}/run", summary="Run a schedule now")
def run_schedule_now(sid: str, ctx: Ctx = Depends(require("report", "ask"))):
    with ctx.svc.db.session() as s:
        r = _mine(s.get(ReportSchedule, sid), ctx, "Schedule")
        s.expunge(r)
    status = automation.run_schedule(ctx.svc.knowledge, ctx.svc.assistant, r)
    with ctx.svc.db.session() as s:
        row = s.get(ReportSchedule, sid)
        row.last_run_at, row.last_status = datetime.now(UTC), status[:300]
    return {"status": status}


@router.patch("/report-schedules/{sid}")
def toggle_schedule(sid: str, enabled: bool, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        r = _mine(s.get(ReportSchedule, sid), ctx, "Schedule")
        r.enabled = enabled
        return _sched_out(r)


@router.delete("/report-schedules/{sid}")
def delete_schedule(sid: str, ctx: Ctx = Depends(require("report"))):
    with ctx.svc.db.session() as s:
        s.delete(_mine(s.get(ReportSchedule, sid), ctx, "Schedule"))
    return {"deleted": sid}


# ----------------------------------------------------------------------------- connectors
class ConnectorBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["folder", "urls", "s3"]
    config: dict = Field(default_factory=dict, description="folder: {path, recursive}; urls: {urls: [...]}; s3: {bucket, prefix}")
    every_hours: int = Field(default=24, ge=1, le=24 * 31)


def _conn_out(c: Connector) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "config": c.config, "every_hours": c.every_hours, "enabled": c.enabled, "workspace": c.workspace,
            "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None, "last_result": c.last_result}


@router.post("/connectors", status_code=201, summary="Keep this workspace in sync with a folder, a list of URLs or an S3 prefix (runs on the scheduler, or on demand)")
def add_connector(body: ConnectorBody, ctx: Ctx = Depends(require("ingest"))):
    try:
        cfg = automation.validate_connector(ctx.svc.knowledge, body.kind, body.config)
    except IngestError as e:
        raise HTTPException(422, str(e))
    with ctx.svc.db.session() as s:
        c = Connector(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, kind=body.kind, name=body.name, config=cfg, every_hours=body.every_hours)
        s.add(c)
        s.flush()
        out = _conn_out(c)
    ctx.audit("connector_add", out["id"], detail={"kind": body.kind})
    return out


@router.get("/connectors")
def list_connectors(ctx: Ctx = Depends(require("ingest"))):
    with ctx.svc.db.session() as s:
        return [_conn_out(c) for c in s.scalars(select(Connector).where(Connector.tenant_id == ctx.principal.tenant_id, Connector.workspace == ctx.scope.workspace).order_by(Connector.created_at))]


@router.post("/connectors/{cid}/sync", summary="Sync now")
def sync_now(cid: str, ctx: Ctx = Depends(require("ingest", "ingest"))):
    with ctx.svc.db.session() as s:
        c = s.get(Connector, cid)
        if not c or c.tenant_id != ctx.principal.tenant_id:
            raise HTTPException(404, "Connector not found")
        s.expunge(c)
    res = automation.sync(ctx.svc.knowledge, c)
    with ctx.svc.db.session() as s:
        row = s.get(Connector, cid)
        row.last_run_at, row.last_result = datetime.now(UTC), res
    ctx.audit("connector_sync", cid, detail={k: v for k, v in res.items() if k != "errors"})
    return res


@router.delete("/connectors/{cid}")
def delete_connector(cid: str, ctx: Ctx = Depends(require("ingest"))):
    with ctx.svc.db.session() as s:
        c = s.get(Connector, cid)
        if not c or c.tenant_id != ctx.principal.tenant_id:
            raise HTTPException(404, "Connector not found")
        s.delete(c)
    return {"deleted": cid}


# ----------------------------------------------------------------------------- annotations
class AnnotationBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=32)
    loc: dict = Field(description="location the note is about, e.g. {\"page\": 3} or {\"sheet\": \"Q1\", \"row\": 5}")
    quote: Optional[str] = Field(default=None, max_length=500)
    note: str = Field(default="", max_length=2000)
    kind: Literal["comment", "highlight", "bookmark"] = "comment"
    shared: bool = False


def _ann_out(a: Annotation, me: str) -> dict:
    return {"id": a.id, "source_id": a.source_id, "loc": a.loc, "quote": a.quote, "note": a.note, "kind": a.kind, "shared": a.shared, "mine": a.user_id == me, "author": a.user_id if a.user_id == me else None,
            "created_at": a.created_at.isoformat()}


@router.post("/annotations", status_code=201, summary="Comment, highlight or bookmark a place in a document you can read")
def add_annotation(body: AnnotationBody, ctx: Ctx = Depends(require("read"))):
    src = ctx.svc.knowledge.store(ctx.scope).get_source(body.source_id, ctx.principal)
    if not src:
        raise HTTPException(404, "Source not found")
    if not isinstance(body.loc, dict) or not body.loc or any(not isinstance(v, (int, str)) for v in body.loc.values()):
        raise HTTPException(422, "loc must be a small object such as {\"page\": 3}")
    with ctx.svc.db.session() as s:
        a = Annotation(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id, workspace=ctx.scope.workspace, doc_key=src.get("doc_key") or src["id"], source_id=src["id"], loc=body.loc,
                       quote=body.quote, note=body.note, kind=body.kind, shared=body.shared)
        s.add(a)
        s.flush()
        return _ann_out(a, ctx.principal.user_id)


@router.get("/annotations", summary="Your annotations and the shared ones on a document")
def list_annotations(source_id: str, ctx: Ctx = Depends(require("read"))):
    src = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not src:
        raise HTTPException(404, "Source not found")
    with ctx.svc.db.session() as s:
        rows = s.scalars(select(Annotation).where(Annotation.tenant_id == ctx.principal.tenant_id, Annotation.doc_key == (src.get("doc_key") or src["id"]))
                         .where((Annotation.user_id == ctx.principal.user_id) | (Annotation.shared.is_(True))).order_by(Annotation.created_at)).all()
        return [_ann_out(a, ctx.principal.user_id) for a in rows]


@router.delete("/annotations/{aid}")
def delete_annotation(aid: str, ctx: Ctx = Depends(require("read"))):
    with ctx.svc.db.session() as s:
        a = s.get(Annotation, aid)
        if not a or a.tenant_id != ctx.principal.tenant_id or (a.user_id != ctx.principal.user_id and ctx.principal.role != "admin"):
            raise HTTPException(404, "Annotation not found")
        s.delete(a)
    return {"deleted": aid}
