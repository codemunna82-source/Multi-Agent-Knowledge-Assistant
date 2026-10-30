from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from ...schemas import IngestResult, SourceInfo, UrlRequest
from ...security.files import safe_filename
from ..deps import Ctx, require

router = APIRouter(prefix="/sources", tags=["sources"])


def info(ctx: Ctx, meta: dict) -> SourceInfo:
    k = ctx.svc.knowledge
    d = {**meta, "needs_reindex": meta.get("embedding") != k.embedder.name}
    return SourceInfo(**{f: d.get(f) for f in SourceInfo.model_fields if f in d})


def _vis(v: str) -> str:
    if v not in ("tenant", "private"):
        raise HTTPException(422, "visibility must be 'tenant' or 'private'")
    return v


def _result(ctx: Ctx, r: dict, name: str) -> IngestResult:
    return IngestResult(status=r["status"], name=name, error=r["error"], source=info(ctx, r["source"]) if r["source"] else None)


def _submit_files(ctx: Ctx, files: list[UploadFile], visibility: str):
    """Stage uploads on disk (size-checked) and enqueue one background job per file; progress via GET /jobs/{id}."""
    limit = ctx.svc.settings.max_upload_mb * 1024 * 1024
    out = []
    for f in files:
        name = safe_filename(f.filename or "upload")
        jid = uuid.uuid4().hex
        d = ctx.svc.jobs.upload_dir(ctx.principal.tenant_id) / jid
        d.mkdir(parents=True)
        path, size, too_big = d / name, 0, False
        with open(path, "wb") as o:
            while chunk := f.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    too_big = True
                    break
                o.write(chunk)
        if too_big or size == 0:
            shutil.rmtree(d, ignore_errors=True)
            out.append({"name": name, "job_id": None, "status": "failed", "error": f"File exceeds the {ctx.svc.settings.max_upload_mb} MB limit" if too_big else "The file is empty"})
            continue
        job_id = ctx.svc.jobs.submit(tenant=ctx.principal.tenant_id, user=ctx.principal.user_id, workspace=ctx.scope.workspace, kind="file", name=name,
                                     payload={"path": str(path), "visibility": visibility})
        ctx.audit("ingest_queued", name, detail={"job_id": job_id, "workspace": ctx.scope.workspace})
        out.append({"name": name, "job_id": job_id, "status": "queued", "error": None})
    return JSONResponse(out, status_code=202)


@router.post("/upload", response_model=list[IngestResult], responses={202: {"description": "async=true: queued job ids"}})
def upload(files: list[UploadFile] = File(...), visibility: str = Form("tenant"), async_: bool = Query(False, alias="async"),
           ctx: Ctx = Depends(require("ingest", "ingest"))):
    """Multi-file upload. Default: synchronous (validated, extracted, embedded and indexed before the response).
    With ?async=true: files are queued for background workers and 202 + job ids are returned."""
    visibility = _vis(visibility)
    if async_:
        return _submit_files(ctx, files, visibility)
    k, limit = ctx.svc.knowledge, ctx.svc.settings.max_upload_mb * 1024 * 1024
    results = []
    for f in files:
        name = safe_filename(f.filename or "upload")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "upload.bin"
            size, too_big = 0, False
            with open(path, "wb") as out:
                while chunk := f.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        too_big = True
                        break
                    out.write(chunk)
            if too_big:
                results.append(IngestResult(status="failed", name=name, error=f"File exceeds the {ctx.svc.settings.max_upload_mb} MB limit"))
            elif size == 0:
                results.append(IngestResult(status="failed", name=name, error="The file is empty"))
            else:
                r = k.ingest_file(ctx.scope, path, name, owner_id=ctx.principal.user_id, visibility=visibility)
                results.append(_result(ctx, r, name))
        ctx.audit("ingest_file", name, "success" if results[-1].status == "ready" else "failed", {"source_id": results[-1].source.id if results[-1].source else None, "workspace": ctx.scope.workspace})
    return results


@router.post("/url", response_model=IngestResult, responses={202: {"description": "async=true: queued job id"}})
def add_url(body: UrlRequest, visibility: str = "tenant", async_: bool = Query(False, alias="async"), ctx: Ctx = Depends(require("ingest", "ingest"))):
    if async_:
        job_id = ctx.svc.jobs.submit(tenant=ctx.principal.tenant_id, user=ctx.principal.user_id, workspace=ctx.scope.workspace, kind="url", name=body.url,
                                     payload={"url": body.url, "visibility": _vis(visibility)})
        ctx.audit("ingest_queued", body.url, detail={"job_id": job_id})
        return JSONResponse([{"name": body.url, "job_id": job_id, "status": "queued", "error": None}], status_code=202)
    r = ctx.svc.knowledge.ingest_url(ctx.scope, body.url, owner_id=ctx.principal.user_id, visibility=_vis(visibility))
    ctx.audit("ingest_url", body.url, "success" if r["status"] == "ready" else "failed", {"workspace": ctx.scope.workspace})
    return _result(ctx, r, body.url)


@router.get("", response_model=list[SourceInfo])
def list_sources(ctx: Ctx = Depends(require("read"))):
    return [info(ctx, m) for m in ctx.svc.knowledge.store(ctx.scope).list_sources(ctx.principal)]


@router.get("/{source_id}", response_model=SourceInfo)
def get_source(source_id: str, ctx: Ctx = Depends(require("read"))):
    m = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    return info(ctx, m)


@router.get("/{source_id}/tables")
def tables(source_id: str, max_rows: int = 200, ctx: Ctx = Depends(require("read"))):
    """Structured tables extracted from the source (spreadsheets, DOCX, HTML, PDF), each with its location."""
    import json

    from ...ingestion.loaders import read_sheets

    st = ctx.svc.knowledge.store(ctx.scope)
    m = st.get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    d = st.source_dir(source_id)
    out: list[dict] = []
    if m.get("tabular"):
        for name, header, data in read_sheets(d / m["original"], m["kind"]):
            loc = {"sheet": name} if name else {}
            out.append({"location": loc, "header": header, "rows": [c for _, c in data[:max_rows]], "total_rows": len(data)})
    elif (d / "tables.json").exists():
        for t in json.loads((d / "tables.json").read_text(encoding="utf-8")):
            out.append({**t, "total_rows": len(t["rows"]), "rows": t["rows"][:max_rows]})
    return out


def _owned(ctx: Ctx, source_id: str) -> dict:
    m = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    if not ctx.principal.can("delete_any") and m.get("owner_id") != ctx.principal.user_id:
        raise HTTPException(403, "Only the owner or an admin may modify this source")
    return m


@router.post("/{source_id}/reindex", response_model=IngestResult)
def reindex(source_id: str, ctx: Ctx = Depends(require("ingest", "ingest"))):
    _owned(ctx, source_id)
    r = ctx.svc.knowledge.reindex(ctx.scope, source_id, ctx.principal)
    ctx.audit("reindex", source_id, "success" if r["status"] == "ready" else "failed")
    return _result(ctx, r, r["name"])


@router.delete("/{source_id}")
def delete_source(source_id: str, ctx: Ctx = Depends(require("delete_own"))):
    _owned(ctx, source_id)
    if not ctx.svc.knowledge.delete(ctx.scope, source_id, ctx.principal):
        raise HTTPException(404, "Source not found")
    ctx.audit("delete_source", source_id, detail={"workspace": ctx.scope.workspace})
    return {"deleted": source_id}
