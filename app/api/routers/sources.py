from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse

from pydantic import BaseModel, Field

from ...schemas import IngestResult, SourceInfo, UrlRequest
from ...security.files import safe_filename
from ..deps import Ctx, page_params, paginate, require

router = APIRouter(prefix="/sources", tags=["sources"])


def info(ctx: Ctx, meta: dict) -> SourceInfo:
    k = ctx.svc.knowledge
    d = {**meta, "needs_reindex": meta.get("embedding") != k.embedder.name}
    return SourceInfo(**{f: d.get(f) for f in SourceInfo.model_fields if f in d})


def _vis(v: str) -> str:
    if v not in ("tenant", "private"):
        raise HTTPException(422, "visibility must be 'tenant' or 'private' (use PUT /sources/{id}/sharing for 'restricted')")
    return v


def _result(ctx: Ctx, r: dict, name: str) -> IngestResult:
    err = r["error"]
    if r["status"] == "duplicate" and r["source"]:
        err = f"Identical to the already indexed '{r['source']['name']}' - not ingested again"
    return IngestResult(status=r["status"], duplicate_of=r.get("duplicate_of"), name=name, error=err, source=info(ctx, r["source"]) if r["source"] else None)


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
def upload(files: list[UploadFile] = File(...), visibility: str = Form("tenant"), allow_duplicate: bool = Form(False), async_: bool = Query(False, alias="async"),
           ctx: Ctx = Depends(require("ingest", "ingest"))):
    """Multi-file upload. Default: synchronous (validated, extracted, embedded and indexed before the response).
    With ?async=true: files are queued for background workers and 202 + job ids are returned.
    An identical file already indexed in the workspace is reported as `duplicate` (unless allow_duplicate); a file with the same name but
    different content becomes a new VERSION of that document (older versions stay available for comparison but are not searched)."""
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
                r = k.ingest_file(ctx.scope, path, name, owner_id=ctx.principal.user_id, visibility=visibility, allow_duplicate=allow_duplicate)
                results.append(_result(ctx, r, name))
        ctx.audit("ingest_file", name, "success" if results[-1].status in ("ready", "duplicate") else "failed", {"source_id": results[-1].source.id if results[-1].source else None, "workspace": ctx.scope.workspace})
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
def list_sources(response: Response, include_versions: bool = False, kind: str | None = None, q: str | None = None, page: tuple[int, int] = Depends(page_params),
                 ctx: Ctx = Depends(require("read"))):
    """Documents visible to you (current versions; include_versions=true adds superseded ones). Paginated: limit/offset, total in X-Total-Count."""
    items = ctx.svc.knowledge.store(ctx.scope).list_sources(ctx.principal, include_old=include_versions)
    if kind:
        items = [m for m in items if m.get("kind") == kind]
    if q:
        items = [m for m in items if q.lower() in m["name"].lower()]
    return [info(ctx, m) for m in paginate(items, response, page)]


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
def delete_source(source_id: str, all_versions: bool = False, ctx: Ctx = Depends(require("delete_own"))):
    """Deletes text, chunks, vectors and the original file. Deleting the current version restores the newest older one; all_versions=true removes the document entirely."""
    _owned(ctx, source_id)
    if not ctx.svc.knowledge.delete(ctx.scope, source_id, ctx.principal, all_versions=all_versions):
        raise HTTPException(404, "Source not found")
    ctx.audit("delete_source", source_id, detail={"workspace": ctx.scope.workspace, "all_versions": all_versions})
    return {"deleted": source_id, "all_versions": all_versions}


@router.get("/{source_id}/versions", response_model=list[SourceInfo])
def versions(source_id: str, ctx: Ctx = Depends(require("read"))):
    m = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    return [info(ctx, v) for v in ctx.svc.knowledge.registry.versions(ctx.scope, m["doc_key"])]


@router.post("/{source_id}/make-current", response_model=SourceInfo)
def make_current(source_id: str, ctx: Ctx = Depends(require("ingest"))):
    """Roll back / forward: make this version the searchable one."""
    m = _owned(ctx, source_id)
    k = ctx.svc.knowledge
    with __import__("app.storage", fromlist=["session_lock"]).session_lock(ctx.scope):
        k.registry.set_current(ctx.scope, source_id)
    ctx.audit("make_current", source_id, detail={"version": m.get("version")})
    return info(ctx, k.store(ctx.scope).get_source(source_id, ctx.principal))


class SharingBody(BaseModel):
    visibility: str = Field(pattern="^(tenant|private|restricted)$")
    users: list[str] = Field(default_factory=list, max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=3)


@router.get("/{source_id}/sharing")
def get_sharing(source_id: str, ctx: Ctx = Depends(require("read"))):
    m = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    return {"visibility": m.get("visibility", "tenant"), "owner_id": m.get("owner_id"), **ctx.svc.knowledge.registry.acl(ctx.scope, m["doc_key"])}


@router.put("/{source_id}/sharing")
def set_sharing(source_id: str, body: SharingBody, ctx: Ctx = Depends(require("share"))):
    """Document-level permissions: 'tenant' (everyone in the organisation), 'private' (owner + admins) or 'restricted' (owner + the listed users/roles + admins)."""
    from sqlalchemy import select

    from ...db import User
    from ...security.auth import normalize_role

    m = _owned(ctx, source_id)
    try:
        roles = [normalize_role(r) for r in body.roles]
    except ValueError as e:
        raise HTTPException(422, str(e))
    with ctx.svc.db.session() as s:  # only users of the same tenant can be granted access
        valid = set(s.scalars(select(User.id).where(User.tenant_id == ctx.principal.tenant_id, User.id.in_(body.users))))
    if set(body.users) - valid:
        raise HTTPException(422, "Unknown user id(s) for this organisation")
    ctx.svc.knowledge.registry.set_visibility(ctx.scope, m["doc_key"], body.visibility, body.users, roles)
    ctx.audit("share_document", source_id, detail={"visibility": body.visibility, "users": len(body.users), "roles": roles})
    return {"visibility": body.visibility, "users": body.users, "roles": roles}
