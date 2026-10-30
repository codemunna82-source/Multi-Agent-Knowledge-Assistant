from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...schemas import IngestResult, SourceInfo, UrlRequest
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


@router.post("/upload", response_model=list[IngestResult])
def upload(files: list[UploadFile] = File(...), visibility: str = Form("tenant"), ctx: Ctx = Depends(require("ingest", "ingest"))):
    """Synchronous multi-file upload: each file is validated, extracted, embedded and indexed before the response."""
    visibility = _vis(visibility)
    k, limit = ctx.svc.knowledge, ctx.svc.settings.max_upload_mb * 1024 * 1024
    results = []
    for f in files:
        name = Path(f.filename or "upload").name
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


@router.post("/url", response_model=IngestResult)
def add_url(body: UrlRequest, visibility: str = "tenant", ctx: Ctx = Depends(require("ingest", "ingest"))):
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
