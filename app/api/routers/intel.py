from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ...intel.entities import extract_source
from ...intel.questions import generate_questions
from ..deps import Ctx, require

router = APIRouter(tags=["intelligence"])


def _src(ctx: Ctx, source_id: str) -> dict:
    m = ctx.svc.knowledge.store(ctx.scope).get_source(source_id, ctx.principal)
    if not m:
        raise HTTPException(404, "Source not found")
    return m


@router.get("/sources/{source_id}/entities")
def entities(source_id: str, types: str | None = Query(None, description="comma separated: NAME,ORG,EMAIL,DATE,MONEY,..."), use_llm: bool = True,
             ctx: Ctx = Depends(require("read"))):
    _src(ctx, source_id)
    k = ctx.svc.knowledge
    units = [u for _, u in k.store(ctx.scope).iter_units([source_id])]
    return extract_source(units, k.llm if use_llm and k.llm.available else None, [t.strip().upper() for t in types.split(",")] if types else None)


@router.get("/sources/{source_id}/questions")
def questions(source_id: str, n: int = Query(8, ge=1, le=20), ctx: Ctx = Depends(require("read"))):
    m, k = _src(ctx, source_id), ctx.svc.knowledge
    return generate_questions(k, k.store(ctx.scope), m, n)


@router.get("/graph")
def graph(entity: str | None = None, to: str | None = None, limit: int = Query(10, ge=1, le=50), ctx: Ctx = Depends(require("read"))):
    """Knowledge graph view: top entities; neighbours of `entity`; or the shortest connection between `entity` and `to`."""
    st = ctx.svc.knowledge.store(ctx.scope)
    kg = ctx.svc.assistant.graphs.get(st, {m["id"] for m in st.list_sources(ctx.principal)})  # graph over visible documents only
    if not entity:
        return {"top": [{"name": kg.nodes[n].name, "type": kg.nodes[n].type, "weight": w} for n, w in kg.top(limit)], "nodes": len(kg.nodes), "edges": kg.G.number_of_edges()}
    ka = kg.find(entity)
    if not ka:
        raise HTTPException(404, "Entity not found")
    if to:
        kb = kg.find(to)
        if not kb:
            raise HTTPException(404, "Target entity not found")
        p = kg.path(ka[0], kb[0])
        return {"path": [kg.nodes[x].name for x in p] if p else None}
    return {"entity": kg.nodes[ka[0]].name, "neighbors": [{"name": kg.nodes[n].name, "type": kg.nodes[n].type, "weight": w} for n, w in kg.neighbors(ka[0], limit)]}


@router.post("/transcribe")
def transcribe(audio: UploadFile = File(...), ctx: Ctx = Depends(require("ask", "ask"))):
    """Speech-to-text for voice queries (OpenAI Whisper). Browsers can alternatively use client-side speech recognition."""
    from ...core import ProviderError
    from ...providers import transcribe_openai

    s = ctx.svc.settings
    if s.llm_provider != "openai" or not s.secret("openai_api_key"):
        raise HTTPException(501, "Server-side transcription needs MKA_LLM_PROVIDER=openai with an API key; use browser speech recognition instead")
    ctype = (audio.content_type or "").split(";")[0]
    if not (ctype.startswith("audio/") or ctype in ("video/webm", "application/ogg")):
        raise HTTPException(415, "Upload an audio file")
    data = audio.file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio larger than 25 MB")
    if not data:
        raise HTTPException(422, "Empty audio")
    try:
        text = transcribe_openai(s, data, audio.filename or "audio.webm", ctype or "audio/webm")
    except ProviderError as e:
        raise HTTPException(502, f"Model/API error: {e}")
    ctx.audit("transcribe", None, detail={"bytes": len(data)})
    return {"text": text}
