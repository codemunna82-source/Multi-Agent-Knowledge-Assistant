"""Document-intelligence operations run by the Summarization Agent: entities, question generation, table extraction, knowledge graph."""
from __future__ import annotations

import json
import re

from ..intel.entities import extract_source
from ..intel.questions import generate_questions
from ..schemas import Citation
from .common import excerpt, result


def named_sources(question: str, metas: list[dict]) -> list[dict]:
    """Sources the question refers to by file name (full name, or stem of >= 3 chars, as whole words)."""
    q = question.lower()
    out = []
    for m in metas:
        name = m["name"].lower()
        stem_ = name.rsplit(".", 1)[0]
        pats = [re.escape(name)] + ([re.escape(stem_)] if len(stem_) >= 3 else [])
        if any(re.search(rf"(?<![\w.]){p}(?![\w])", q) for p in pats):
            out.append(m)
    return out


def _targets(ag, state, cap: int = 5) -> list[dict]:
    c = ag.ctx(state)
    metas = c.sources(ag.k)
    if c.req.source_ids is None:
        metas = named_sources(state["question"], metas) or metas
    return metas[:cap]


def run_entities(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    metas = [m for m in _targets(ag, state) if not m.get("tabular")]
    if not metas:
        return {"draft": ag._no_sources("summarize")}
    st = k.store(c.scope)
    lines, cites, details = [], [], {}
    for m in metas:
        r = extract_source([u for _, u in st.iter_units([m["id"]])], k.llm if k.llm.available else None)
        details[m["name"]] = r["entities"]
        lines.append(f"{m['name']} ({r['method']}):")
        for typ, ents in r["entities"].items():
            lines.append(f"  {typ}: " + "; ".join(f"{e['value']} ×{e['count']}" for e in ents[:8]))
            for e in ents[:2]:
                cites.append(Citation(source_id=m["id"], source=m["name"], location=e["locations"][0] if e["locations"] else "document", excerpt=f"{typ}: {e['value']}"))
    if not details or not any(details.values()):
        d = result("summarize", "No entities were detected in the selected sources.", confidence="medium", limitations=["The built-in extractor recognises emails, URLs, phones, money, dates, percentages, IDs and capitalised names/organisations (Latin script)."])
    else:
        lim = ["Entities were found by " + ("a heuristic extractor plus an LLM (LLM values are kept only if they appear verbatim in the text)." if k.llm.available else
                "a heuristic extractor (regex + capitalisation rules); names in non-Latin scripts and unusual formats may be missed. Configure an LLM for broader extraction.")]
        d = result("summarize", "\n".join(lines), confidence="medium", citations=cites[:30], limitations=lim, details={"entities": details})
    d["skip_verify"] = True
    return {"draft": d, "evidence": [], "trace": [f"summarize/entities: {len(metas)} source(s)"]}


def run_questions(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    metas = _targets(ag, state, 3)
    if not metas:
        return {"draft": ag._no_sources("summarize")}
    st = k.store(c.scope)
    out, lines = {}, []
    for m in metas:
        r = generate_questions(k, st, m)
        out[m["name"]] = r
        lines.append(f"{m['name']} ({r['method']}):\n" + "\n".join(f"  {i}. {q}" for i, q in enumerate(r["questions"], 1)))
    d = result("summarize", "\n\n".join(lines), confidence="medium", details={"questions": out},
               limitations=["Questions are suggestions derived from the document content; answers are produced only when you ask them."])
    d["skip_verify"] = True
    return {"draft": d, "evidence": [], "trace": [f"summarize/questions: {len(metas)} source(s)"]}


def run_tables(ag, state) -> dict:
    from ..ingestion.loaders import read_sheets

    c, k = ag.ctx(state), ag.k
    metas = _targets(ag, state)
    st = k.store(c.scope)
    blocks, cites = [], []
    for m in metas:
        d = st.source_dir(m["id"])
        tabs = []
        if m.get("tabular"):
            tabs = [{"location": {"sheet": n} if n else {}, "header": h, "rows": [cells for _, cells in rows[:3]], "total_rows": len(rows)} for n, h, rows in read_sheets(d / m["original"], m["kind"])]
        elif (d / "tables.json").exists():
            tabs = [{**t, "total_rows": len(t["rows"]), "rows": t["rows"][:3]} for t in json.loads((d / "tables.json").read_text(encoding="utf-8"))]
        for t in tabs:
            from ..core import format_loc

            loc = format_loc(t["location"]) if t["location"] else "table"
            md = "| " + " | ".join(t["header"]) + " |\n|" + "---|" * len(t["header"]) + "\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in t["rows"])
            blocks.append(f"{m['name']} — {loc} ({t['total_rows']} rows):\n{md}")
            cites.append(Citation(source_id=m["id"], source=m["name"], location=loc, excerpt=excerpt(" | ".join(t["header"]), 200)))
    if not blocks:
        d = result("summarize", "No tables were found in the selected sources.", confidence="medium", limitations=["Tables are detected in spreadsheets, DOCX, HTML pages and ruled PDF tables."])
    else:
        d = result("summarize", "\n\n".join(blocks[:8]), confidence="high", citations=cites[:20], limitations=["Only the first rows of each table are shown; use GET /sources/{id}/tables for the full data."],
                   details={"tables": len(blocks)})
    d["skip_verify"] = True
    return {"draft": d, "evidence": [], "trace": [f"summarize/tables: {len(blocks)} table(s)"]}


def run_graph(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    metas = c.sources(k)
    if not metas:
        return {"draft": ag._no_sources("summarize")}
    st = k.store(c.scope)
    allowed = {m["id"] for m in metas}
    kg = ag.a.graphs.get(st, allowed)
    idx = ag.a.pipeline.cache.index(st)

    def chunk_cite(cid: str):
        ch = idx.by_id.get(cid)
        if not ch or cid.split(":", 1)[0] not in allowed:
            return None
        from ..core import format_loc

        sid = cid.split(":", 1)[0]
        return Citation(source_id=sid, source=idx.metas[sid]["name"], location=format_loc(ch["loc"], ch.get("loc_end")), excerpt=excerpt(ch["text"]))

    keys = kg.find(state["question"])
    cites, lim = [], ["Relations are co-mentions in the same passage (graph edges link back to the verbatim text); relation types are not inferred."]
    if len(keys) >= 2:
        a, b = keys[0], keys[1]
        path = kg.path(a, b)
        if not path:
            d = result("summarize", f"No connection between “{kg.nodes[a].name}” and “{kg.nodes[b].name}” was found in the indexed documents.", confidence="medium", limitations=lim, details={"graph": {"path": None}})
        else:
            names = [kg.nodes[p].name for p in path]
            for u, v in zip(path, path[1:]):
                for cid in kg.G[u][v]["chunks"][:2]:
                    ci = chunk_cite(cid)
                    if ci:
                        cites.append(ci)
            hops = len(path) - 1
            ans = (f"“{names[0]}” and “{names[-1]}” are mentioned together in {kg.G[a][b]['weight']} passage(s)." if hops == 1 else
                   f"“{names[0]}” is connected to “{names[-1]}” through {hops} hops: " + " → ".join(names) + ".")
            d = result("summarize", ans, confidence="high" if hops == 1 else "medium", citations=cites, limitations=lim, details={"graph": {"path": names, "hops": hops}})
    elif len(keys) == 1:
        nb = kg.neighbors(keys[0], 10)
        name = kg.nodes[keys[0]].name
        if not nb:
            d = result("summarize", f"“{name}” appears in the documents but is not mentioned together with any other known entity.", confidence="medium", limitations=lim)
        else:
            for n, _ in nb[:3]:
                for cid in kg.G[keys[0]][n]["chunks"][:1]:
                    ci = chunk_cite(cid)
                    if ci:
                        cites.append(ci)
            d = result("summarize", f"Entities mentioned together with “{name}”: " + "; ".join(f"{kg.nodes[n].name} ({w})" for n, w in nb) + ".", confidence="high", citations=cites, limitations=lim,
                       details={"graph": {"entity": name, "neighbors": [{"name": kg.nodes[n].name, "type": kg.nodes[n].type, "weight": w} for n, w in nb]}})
    else:
        top = kg.top(10)
        if not top:
            d = result("summarize", "No entities were found to build a graph from.", limitations=lim)
        else:
            d = result("summarize", "I could not find a known entity in the question. Most connected entities: " + "; ".join(f"{kg.nodes[n].name} ({w})" for n, w in top) + ".",
                       confidence="low", limitations=lim, details={"graph": {"top": [kg.nodes[n].name for n, _ in top]}})
    d["skip_verify"] = True
    return {"draft": d, "evidence": [], "trace": [f"summarize/graph: {len(keys)} entity match(es)"]}
