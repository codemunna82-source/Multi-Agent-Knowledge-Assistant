"""Comparison Agent: document vs document, version vs version, topic-focused evidence comparison and contradiction detection.

Deterministic alignment (sentence diff) gives exact, citable differences with locations; an LLM is only used to write the
topic comparison from retrieved evidence and to confirm contradiction candidates."""
from __future__ import annotations

import re
from dataclasses import replace

from ..core import ProviderError, format_loc, tokenize
from ..intel import compare as cmp
from ..intel import contradict as contra
from ..schemas import Citation
from ..security.injection import SYSTEM_GUARD, wrap_untrusted
from .common import NOT_VERIFIED, best_sentences, evidence_citations, excerpt, hit_to_evidence, result, split_sentences
from .intel_ops import named_sources
from .routing import COMPARE

CONTRA_Q = re.compile(r"\b(contradict\w*|conflict\w*|inconsisten\w*|disagree\w*|mismatch\w*)\b", re.I)
VERSION_Q = re.compile(r"\b(versions?|revisions?|what(?:'s| has| have)? changed|changes?|changed|updated?|newer|older|previous|latest)\b", re.I)
MAX_SENT_PER_DOC = 3000


def _units(st, meta):
    return [u for _, u in st.iter_units([meta["id"]])]


def _topic(question: str, metas: list[dict]) -> str:
    q = COMPARE.sub(" ", question)
    for m in metas:
        for n in (m["name"], m["name"].rsplit(".", 1)[0]):
            q = re.sub(re.escape(n), " ", q, flags=re.I)
    q = re.sub(r"\b(between|and|the|with|of|these|two|documents?|files?|sources?|versions?|vs|in|on|about|regarding|all|any|are|is|there|do|does|they|them|each|other)\b", " ", q, flags=re.I)
    return " ".join(q.split(" ")).strip(" ?.!,;:")


def _cites(items, a, b, per_side=3):
    out = []
    for side, meta in (("before", a), ("after", b)):
        for it in items[:per_side]:
            node = it.get(side) or (it if side == "after" and "text" in it else None)
            if node:
                out.append(Citation(source_id=meta["id"], source=meta["name"], location=format_loc(node["loc"]), excerpt=excerpt(node["text"], 220), loc=node["loc"], version=meta.get("version")))
    return out


def _fmt_diff(d: dict, a: dict, b: dict, limit=5) -> str:
    s = d["summary"]
    la, lb = f"{a['name']}" + (f" v{a['version']}" if a.get("version") else ""), f"{b['name']}" + (f" v{b['version']}" if b.get("version") else "")
    lines = [f"{la} → {lb}: {s['unchanged']} unchanged, {s['changed']} changed, {s['added']} added, {s['removed']} removed sentence(s) (similarity {s['similarity']:.0%})."]
    for ch in d["changed"][:limit]:
        nums = "; ".join(f"{x['from']} → {x['to']}" for x in ch["number_changes"][:3])
        lines.append(f"- Changed ({format_loc(ch['before']['loc'])} → {format_loc(ch['after']['loc'])}){' [' + nums + ']' if nums else ''}: “{excerpt(ch['before']['text'], 110)}” → “{excerpt(ch['after']['text'], 110)}”")
    for x in d["added"][:limit]:
        lines.append(f"- Only in {lb} ({format_loc(x['loc'])}): “{excerpt(x['text'], 140)}”")
    for x in d["removed"][:limit]:
        lines.append(f"- Only in {la} ({format_loc(x['loc'])}): “{excerpt(x['text'], 140)}”")
    return "\n".join(lines)


def _diff_answer(st, a, b, route_note: str) -> dict:
    structured = bool(a.get("tabular") or b.get("tabular"))
    d = cmp.compare_units(_units(st, a), _units(st, b), structured)
    cites = _cites(d["changed"], a, b) + [Citation(source_id=b["id"], source=b["name"], location=format_loc(x["loc"]), excerpt=excerpt(x["text"], 220), loc=x["loc"], version=b.get("version")) for x in d["added"][:3]] \
        + [Citation(source_id=a["id"], source=a["name"], location=format_loc(x["loc"]), excerpt=excerpt(x["text"], 220), loc=x["loc"], version=a.get("version")) for x in d["removed"][:3]]
    lim = ["Sentences are aligned deterministically; a re-ordered but unchanged passage can show up as removed + added.", route_note]
    if d["truncated"]:
        lim.append(f"Only the first {cmp.MAX_SEGMENTS} sentences of each document were compared.")
    out = result("compare", _fmt_diff(d, a, b), confidence="high", citations=cites, limitations=lim, details={"diff": d, "left": a["name"], "right": b["name"]})
    out["skip_verify"] = True
    return out


def _passages(st, metas: list[dict]) -> list[dict]:
    out = []
    for m in metas:
        n = 0
        for u in _units(st, m):
            for s in split_sentences(u.text, m.get("tabular", False)):
                if len(s) >= 25:
                    out.append({"source_id": m["id"], "source": m["name"], "loc": u.loc, "text": s})
                    n += 1
                    if n >= MAX_SENT_PER_DOC:
                        break
            if n >= MAX_SENT_PER_DOC:
                break
    return out


def _contradiction_answer(ag, st, metas, extra_passages=None) -> dict:
    k = ag.k
    passages = extra_passages or _passages(st, metas)
    res = contra.find(passages, k.llm if k.llm.available else None, cross_only=len({p["source_id"] for p in passages}) > 1)
    items = res["contradictions"]
    label = "confirmed" if res["method"] == "llm" else "candidate"
    if not items:
        ans = f"No {'contradictions' if res['method'] == 'llm' else 'candidate contradictions'} were found between {', '.join(m['name'] for m in metas)}."
        conf = "medium"
    else:
        lines = []
        for c in items[:8]:
            lines.append(f"- [{c['type']}] {c['a']['source']} ({format_loc(c['a']['loc'])}): “{excerpt(c['a']['text'], 150)}”  ⟷  {c['b']['source']} ({format_loc(c['b']['loc'])}): “{excerpt(c['b']['text'], 150)}”"
                         + (f" — {c['reason']}" if c.get("reason") else ""))
        ans = f"{len(items)} {label} contradiction(s):\n" + "\n".join(lines)
        conf = "medium" if res["method"] == "llm" else "low"
    cites = []
    for c in items[:10]:
        for side in ("a", "b"):
            n = c[side]
            cites.append(Citation(source_id=n["source_id"], source=n["source"], location=format_loc(n["loc"]), excerpt=excerpt(n["text"], 220), loc=n["loc"]))
    lim = (["Heuristic detector (numbers, negation, antonyms): these are candidates to review, not confirmed contradictions. Configure an LLM to have each pair judged."]
           if res["method"] == "heuristic" else ["Each candidate pair was judged by the language model; confirmed pairs only."])
    out = result("compare", ans, confidence=conf, citations=cites, limitations=lim, details={"contradictions": items, "method": res["method"], "candidates_examined": res["candidates_examined"]})
    out["skip_verify"] = True
    return out


def _topic_compare(ag, state, c, metas, topic) -> dict:
    k = ag.k
    st = k.store(c.scope)
    per, evidence, missing = {}, [], []
    for m in metas[:6]:
        res = ag.a.pipeline.retrieve(st, topic, replace(c.opts, top_k=3, filters=c.opts.filters), [m["id"]], (c.last or {}).get("question"), c.summary)
        if res.hits:
            per[m["name"]] = res.hits
            evidence.extend(res.hits)
        else:
            missing.append(m["name"])
    if not per:
        d = result("compare", NOT_VERIFIED + " None of the sources has relevant passages for this comparison.")
        d["abstained"] = True
        return {"draft": d}
    ev = [hit_to_evidence(i, h) for i, h in enumerate(evidence, 1)]
    lim = [f"No relevant evidence found in: {', '.join(missing)}"] if missing else []
    extra = contra.find([{"source_id": e["source_id"], "source": e["source"], "loc": e.get("loc") or {}, "text": s} for e in ev for s in split_sentences(e["context"]) if len(s) >= 25], None)
    conflicts = extra["contradictions"][:3]
    if k.llm.available:
        body = "\n".join(f"[{e['i']}] SOURCE {e['source']}\n" + wrap_untrusted(excerpt(e["context"], 800), e["source"]) for e in ev)
        system = ("Compare the sources using ONLY the evidence. List matches and conflicts, cite evidence as [n] and name the source for every claim. Say so when evidence is missing. " + SYSTEM_GUARD)
        try:
            d = result("compare", k.llm.complete(system, f"Task: {state['question']}\n\n{body}"), confidence="medium", citations=evidence_citations(ev), limitations=lim,
                       details={"candidate_conflicts": conflicts})
            d["generated"] = True
            return {"draft": d, "evidence": ev, "trace": [f"compare: topic across {len(per)} sources (llm)"]}
        except ProviderError as e:
            lim.append(f"LLM unavailable ({e}); showing side-by-side evidence.")
    else:
        lim.append("No LLM configured: the evidence from each source is shown side by side with heuristic conflict candidates.")
    body = "\n\n".join(f"{name}:\n" + "\n".join(f"- {sent} [{e['location']}]" for e, sent in best_sentences([x for x in ev if x["source"] == name], topic, 2)) for name in per)
    if conflicts:
        body += "\n\nPossible conflicts (heuristic):\n" + "\n".join(f"- {x['a']['source']}: “{excerpt(x['a']['text'], 100)}” ⟷ {x['b']['source']}: “{excerpt(x['b']['text'], 100)}”" for x in conflicts)
    d = result("compare", "Evidence from each source on this topic:\n\n" + body, confidence="low", citations=evidence_citations(ev), limitations=lim, details={"candidate_conflicts": conflicts})
    d["skip_verify"] = True
    return {"draft": d, "evidence": ev, "trace": [f"compare: topic across {len(per)} sources (side by side)"]}


def run_compare(ag, state) -> dict:
    c, k = ag.ctx(state), ag.k
    all_metas = c.sources(k)
    st = k.store(c.scope)
    q = state["question"]
    metas = all_metas if c.req.source_ids is not None else (named_sources(q, all_metas) or all_metas)
    # --- version change detection: "what changed in policy.pdf?" (one document with older versions retained)
    if VERSION_Q.search(q) and len(metas) >= 1 and not CONTRA_Q.search(q):
        for m in (metas if len(metas) == 1 else []):
            vers = [v for v in k.registry.versions(c.scope, m.get("doc_key") or m["id"]) if st.get_source(v["id"], c.principal)]
            if len(vers) >= 2:
                new, old = vers[0], vers[1]
                d = _diff_answer(st, old, new, f"Compared version {old['version']} with version {new['version']} of {m['name']}.")
                return {"draft": d, "evidence": [], "trace": [f"compare: versions {old['version']}→{new['version']}"]}
    if len(metas) < 2:
        return {"draft": result("compare", "Comparison needs at least two documents (or two versions of one document).", limitations=["Upload another document, select two with source_ids, or re-upload a changed file to create a new version."])}
    metas = metas[:6]
    if CONTRA_Q.search(q):
        topic = _topic(q, metas)
        if len(tokenize(topic)) >= 2:  # contradictions about a topic: only the relevant passages
            rr = ag.a.pipeline.retrieve(st, topic, replace(c.opts, top_k=10), [m["id"] for m in metas], None, None)
            ps = [{"source_id": h.source_id, "source": h.source, "loc": h.loc or {}, "text": s} for h in rr.hits for s in split_sentences(h.llm_text) if len(s) >= 25]
            d = _contradiction_answer(ag, st, metas, ps or None)
        else:
            d = _contradiction_answer(ag, st, metas)
        return {"draft": d, "evidence": [], "trace": [f"compare: contradictions across {len(metas)} sources ({d['details']['method']})"]}
    topic = _topic(q, metas)
    if len(tokenize(topic)) >= 2:
        return _topic_compare(ag, state, c, metas, topic)
    if len(metas) == 2:
        d = _diff_answer(st, metas[0], metas[1], "Whole-document comparison (no specific topic named).")
        return {"draft": d, "evidence": [], "trace": ["compare: whole-document diff"]}
    d = result("compare", "Which aspect should I compare across these documents? Name a topic, or select exactly two documents for a full comparison.", needs_input=True,
               limitations=[f"{len(metas)} documents were in scope."])
    return {"draft": d, "trace": ["compare: topic needed for >2 documents"]}
