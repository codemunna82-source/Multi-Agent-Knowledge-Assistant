"""Summarization Agent: summaries, cross-document comparison and (Phase 5) document-intelligence operations."""
from __future__ import annotations

from ..core import ProviderError
from ..schemas import Citation
from ..security.injection import SYSTEM_GUARD, wrap_untrusted
from ..tools.summarise import summarise_chunks
from .common import NOT_VERIFIED, best_sentences, evidence_citations, excerpt, hit_to_evidence, result
from .routing import COMPARE


def run_summarize(ag, state) -> dict:
    sub = (state.get("plan") or {}).get("sub") or "summary"
    fn = {"summary": _summary, "compare": _compare}.get(sub)
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


def _compare(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    metas = c.sources(k)
    if len(metas) < 2:
        return {"draft": result("summarize", "Comparison needs at least two sources.", limitations=["Add another source or select two with source_ids."])}
    topic = COMPARE.sub(" ", state["query"])
    per, evidence, missing = {}, [], []
    from dataclasses import replace

    st = k.store(c.scope)
    for m in metas[:6]:
        res = ag.a.pipeline.retrieve(st, topic, replace(c.opts, top_k=3, filters=c.opts.filters), [m["id"]], (c.last or {}).get("question"), c.summary)
        if res.hits:
            per[m["name"]] = res.hits
            evidence.extend(res.hits)
        else:
            missing.append(m["name"])
    if not per:
        d = result("summarize", NOT_VERIFIED + " None of the sources has relevant passages for this comparison.")
        d["abstained"] = True
        return {"draft": d}
    ev = [hit_to_evidence(i, h) for i, h in enumerate(evidence, 1)]
    lim = [f"No relevant evidence found in: {', '.join(missing)}"] if missing else []
    if k.llm.available:
        body = "\n".join(f"[{e['i']}] SOURCE {e['source']}\n" + wrap_untrusted(excerpt(e["context"], 800), e["source"]) for e in ev)
        system = ("Compare the sources using ONLY the evidence. List matches and conflicts, cite evidence as [n] and name the source for every claim. Say so when evidence is missing. " + SYSTEM_GUARD)
        try:
            d = result("summarize", k.llm.complete(system, f"Task: {state['question']}\n\n{body}"), confidence="medium", citations=evidence_citations(ev), limitations=lim)
            d["generated"] = True
            return {"draft": d, "evidence": ev, "trace": [f"summarize: compare {len(per)} sources (llm)"]}
        except ProviderError as e:
            lim.append(f"LLM unavailable ({e}); showing side-by-side evidence.")
    else:
        lim.append("No LLM configured: automatic match/conflict analysis is unavailable, so the evidence from each source is shown side by side.")
    body = "\n\n".join(f"{name}:\n" + "\n".join(f"- {sent} [{e['location']}]" for e, sent in best_sentences([x for x in ev if x["source"] == name], topic, 2)) for name in per)
    d = result("summarize", "Evidence from each source on this topic:\n\n" + body, confidence="low", citations=evidence_citations(ev), limitations=lim)
    d["skip_verify"] = True
    return {"draft": d, "evidence": ev, "trace": [f"summarize: compare {len(per)} sources (side by side)"]}
