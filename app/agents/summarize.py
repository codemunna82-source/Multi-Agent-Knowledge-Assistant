"""Summarization Agent: summaries, cross-document comparison and (Phase 5) document-intelligence operations."""
from __future__ import annotations

from ..schemas import Citation
from ..tools.summarise import summarise_chunks
from .common import excerpt, result


def run_summarize(ag, state) -> dict:
    sub = (state.get("plan") or {}).get("sub") or "summary"
    fn = {"summary": _summary}.get(sub)
    if sub in ("entities", "questions", "tables", "graph"):
        from . import intel_ops

        fn = getattr(intel_ops, f"run_{sub}")
    return fn(ag, state)


def _summary(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    metas = c.sources(k)
    if not metas:
        return {"draft": ag._no_sources("summarize")}
    q = state["question"].lower()
    if c.req.source_ids is None:
        named = [m for m in metas if m["name"].lower() in q or m["name"].rsplit(".", 1)[0].lower() in q]
        metas = named or metas
    st = k.store(c.scope)
    parts, cites, lim = [], [], []
    llm_used = False
    for m in metas[:10]:
        if m.get("tabular"):
            cols = "; ".join(f"{(t['sheet'] + ': ') if t['sheet'] else ''}{t['rows']} rows, columns {', '.join(t['columns'])}" for t in m.get("tables", []))
            text = f"Spreadsheet with {cols}."
        else:
            text, _ = summarise_chunks(st.load_chunks(m["id"]), k.llm if k.llm.available else None)
            llm_used = llm_used or k.llm.available
        parts.append(f"{m['name']}:\n{text}" if len(metas) > 1 else text)
        cites.append(Citation(source_id=m["id"], source=m["name"], location=f"entire source ({m.get('chunks', '?')} chunks)", excerpt=excerpt(text, 200)))
    if len(metas) > 10:
        lim.append("Only the first 10 sources were summarised.")
    lim.append("Built from every chunk of the source(s) in batches (map-reduce)." + ("" if llm_used else " No LLM configured: extractive summary of key sentences."))
    d = result("summarize", "\n\n".join(parts), confidence="medium", citations=cites, limitations=lim + ag._stale(metas)[:5])
    d["skip_verify"] = True  # summaries are map-reduced over whole documents, not a retrieved-evidence answer
    return {"draft": d, "evidence": [], "trace": [f"summarize: {len(metas)} source(s)"]}
