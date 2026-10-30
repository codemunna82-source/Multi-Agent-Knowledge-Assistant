from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..deps import Ctx, require

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: str
    name: str
    kind: str
    status: str  # queued | running | ready | failed
    stage: Optional[str] = None
    progress: int = 0
    attempts: int = 0
    error: Optional[str] = None
    source_id: Optional[str] = None
    workspace: str
    created_at: str
    updated_at: str


def out(j) -> JobOut:
    return JobOut(id=j.id, name=j.name, kind=j.kind, status=j.status, stage=j.stage, progress=j.progress, attempts=j.attempts, error=j.error,
                  source_id=j.source_id, workspace=j.workspace, created_at=j.created_at.isoformat(), updated_at=j.updated_at.isoformat())


def _user_filter(ctx: Ctx):
    return None if ctx.principal.can("delete_any") else ctx.principal.user_id  # admins see the whole tenant's jobs


@router.get("", response_model=list[JobOut])
def list_jobs(ctx: Ctx = Depends(require("ingest")), limit: int = Query(50, le=200), all_workspaces: bool = False):
    return [out(j) for j in ctx.svc.jobs.list(ctx.principal.tenant_id, _user_filter(ctx), None if all_workspaces else ctx.scope.workspace, limit)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: Ctx = Depends(require("ingest"))):
    j = ctx.svc.jobs.get(job_id, ctx.principal.tenant_id, _user_filter(ctx))
    if not j:
        raise HTTPException(404, "Job not found")
    return out(j)
