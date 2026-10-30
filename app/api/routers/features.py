"""Task-oriented API groups on top of the same services the chat uses: exact search, summaries, comparison / change detection, web research."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ...agents.common import split_sentences
from ...core import ProviderError, format_loc
from ...intel import compare as cmp
from ...intel import contradict as contra
from ...intel.summaries import STYLES, summarize_source
from ...schemas import AskRequest, AskResponse
from ...tools.exact import exact_search
from ..deps import Ctx, page_params, require

router = APIRouter(tags=["search & analysis"])


def _metas(ctx: Ctx, ids: list[str] | None, need: int = 1) -> list[dict]:
    st = ctx.svc.knowledge.store(ctx.scope)
    metas = st.list_sources(ctx.principal)
    if ids:
        by = {m["id"]: m for m in metas}
        missing = [i for i in ids if i not in by]
        if missing:
            raise HTTPException(404, "Unknown source id(s): " + ", ".join(missing))
        metas = [by[i] for i in ids]
    if len(metas) < need:
        raise HTTPException(404 if not metas else 422, "No sources available" if not metas else f"Needs at least {need} sources")
    return metas


# ----------------------------------------------------------------------------- exact search
class ExactBody(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    source_ids: Optional[list[str]] = Field(default=None, max_length=50)
    case_sensitive: bool = False
    whole_word: bool = True


@router.post("/search/exact", summary="Literal name / phrase / ID search over the COMPLETE extracted text: counts per document, pages, paginated matches")
def exact(body: ExactBody, response: Response, page: tuple[int, int] = Depends(page_params), ctx: Ctx = Depends(require("search", "ask"))):
    limit, offset = page
    metas = _metas(ctx, body.source_ids)
    st = ctx.svc.knowledge.store(ctx.scope)
    r = exact_search(st.iter_units([m["id"] for m in metas]), body.term, case_sensitive=body.case_sensitive, whole_word=body.whole_word, max_excerpts=20000)  # the page list and totals cover every match; only the excerpts are paginated
    pages: dict[str, list[int]] = {}
    for m in r.matches:
        if "page" in m["loc"]:
            pages.setdefault(m["source"], [])
            if m["loc"]["page"] not in pages[m["source"]]:
                pages[m["source"]].append(m["loc"]["page"])
    response.headers["X-Total-Count"] = str(r.count)
    ctx.audit("exact_search", None, detail={"count": r.count, "sources": len(metas)})
    return {"term": r.term, "count": r.count, "locations_with_match": r.units_with_match, "by_source": list(r.by_source.values()), "pages": {k: sorted(v) for k, v in pages.items()},
            "matches": r.matches[offset:offset + limit], "limit": limit, "offset": offset, "pages_listing_complete": not r.truncated, "rules": r.rules, "sources_searched": len(metas)}


# ----------------------------------------------------------------------------- summaries
class SummaryBody(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=10)
    style: Literal["short", "detailed", "executive", "chapter", "section"] = "detailed"
    section: Optional[str] = Field(default=None, max_length=200, description="title (or part of it) for style=section")


@router.post("/summaries", summary=f"Summaries of whole documents: {', '.join(STYLES)}")
def summaries(body: SummaryBody, ctx: Ctx = Depends(require("summarize", "ask"))):
    metas = _metas(ctx, body.source_ids)
    st, k = ctx.svc.knowledge.store(ctx.scope), ctx.svc.knowledge
    out = []
    for m in metas:
        try:
            out.append(summarize_source(k, st, m, body.style, body.section))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ProviderError as e:
            raise HTTPException(502, f"Model/API error: {e}")
    ctx.audit("summarize", None, detail={"style": body.style, "sources": len(metas)})
    return {"style": body.style, "summaries": out, "llm": k.llm.available}


# ----------------------------------------------------------------------------- comparison
class CompareBody(BaseModel):
    source_ids: list[str] = Field(min_length=2, max_length=6)
    mode: Literal["diff", "contradictions"] = "diff"


@router.post("/compare", summary="Compare two documents (sentence-level diff) or find contradictions between 2-6 documents")
def compare(body: CompareBody, ctx: Ctx = Depends(require("compare", "ask"))):
    metas = _metas(ctx, body.source_ids, need=2)
    st, k = ctx.svc.knowledge.store(ctx.scope), ctx.svc.knowledge
    if body.mode == "diff":
        if len(metas) != 2:
            raise HTTPException(422, "A diff compares exactly two documents")
        a, b = metas
        d = cmp.compare_units([u for _, u in st.iter_units([a["id"]])], [u for _, u in st.iter_units([b["id"]])], bool(a.get("tabular") or b.get("tabular")))
        ctx.audit("compare", None, detail={"mode": "diff"})
        return {"mode": "diff", "left": {"id": a["id"], "name": a["name"], "version": a.get("version")}, "right": {"id": b["id"], "name": b["name"], "version": b.get("version")}, **d}
    passages = []
    for m in metas:
        n = 0
        for _, u in st.iter_units([m["id"]]):
            for s in split_sentences(u.text, bool(m.get("tabular"))):
                if len(s) >= 25 and n < 3000:
                    passages.append({"source_id": m["id"], "source": m["name"], "loc": u.loc, "text": s})
                    n += 1
    res = contra.find(passages, k.llm if k.llm.available else None)
    for c in res["contradictions"]:
        for side in ("a", "b"):
            c[side]["location"] = format_loc(c[side]["loc"])
    ctx.audit("compare", None, detail={"mode": "contradictions", "found": len(res["contradictions"])})
    return {"mode": "contradictions", **res, "note": "Heuristic candidates - review each pair." if res["method"] == "heuristic" else "Pairs confirmed by the language model."}


@router.get("/sources/{source_id}/changes", summary="What changed between a document version and its predecessor (or a chosen version)")
def changes(source_id: str, against: Optional[str] = None, ctx: Ctx = Depends(require("compare", "ask"))):
    k = ctx.svc.knowledge
    st = k.store(ctx.scope)
    meta = st.get_source(source_id, ctx.principal)
    if not meta:
        raise HTTPException(404, "Source not found")
    vers = [v for v in k.registry.versions(ctx.scope, meta.get("doc_key") or source_id) if st.get_source(v["id"], ctx.principal)]
    if against:
        old = next((v for v in vers if v["id"] == against), None)
        if old is None:
            raise HTTPException(404, "Version not found for this document")
    else:
        older = [v for v in vers if v["version"] < meta["version"]]
        if not older:
            raise HTTPException(409, "This is the first version: nothing to compare against")
        old = older[0]
    d = cmp.compare_units([u for _, u in st.iter_units([old["id"]])], [u for _, u in st.iter_units([source_id])], bool(meta.get("tabular")))
    return {"document": meta["name"], "from_version": old["version"], "to_version": meta["version"], "from_id": old["id"], "to_id": source_id, **d}


# ----------------------------------------------------------------------------- web research
class WebBody(BaseModel):
    query: str = Field(min_length=3, max_length=1000, description="question; may contain URLs to read. Without a URL the configured search provider is used")


@router.post("/web/research", response_model=AskResponse, summary="Web research (approved sources only). Answers cite web pages with origin=web, kept apart from your documents")
def web_research(body: WebBody, request: Request, ctx: Ctx = Depends(require("web", "ask"))):
    try:
        resp = ctx.svc.assistant.ask(ctx.scope, AskRequest(question=body.query, force_route="web", incognito=True), ctx.principal, conversation_id=f"web-{request.state.request_id}")
    except ProviderError as e:
        raise HTTPException(502, f"Model/API error: {e}")
    ctx.svc.assistant.forget(ctx.scope, f"web-{request.state.request_id}", ctx.principal.user_id)
    ctx.audit("web_research", None, detail={"route": resp.route})
    resp.request_id = request.state.request_id
    return resp
