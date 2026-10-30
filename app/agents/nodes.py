"""The agents. Each node is a small, separately testable unit that reads/writes the checkpointed AgentState and uses only
registered tools. Generative agents (semantic, document_search, web, summarize) are followed by the Verification Agent."""
from __future__ import annotations

import re
from typing import Optional

from .. import web_search
import logging

from ..core import IngestError, ProviderError, format_loc
from ..providers import track_usage
from ..intel.language import detect_language, language_name
from ..schemas import Citation
from ..security.injection import SYSTEM_GUARD, guard_output, scan_text, wrap_untrusted
from ..tools import tabular as tab
from .common import NOT_VERIFIED, best_sentences, confidence_from, evidence_citations, excerpt, hit_to_evidence, result
from .routing import URL, llm_route, rules_route
from .state import AgentState, RunCtx
from .tools import ToolError

log = logging.getLogger("mka.agent")

ANSWER_SYSTEM = ("Answer the question using ONLY the numbered evidence. Cite evidence inline as [n]. If the evidence does not contain the answer, say you could not verify it. "
                 "Be concise. Do not invent numbers, names or dates.")


class Agents:
    def __init__(self, assistant):
        self.a = assistant
        self.k = assistant.k
        self.tools = assistant.tools

    def ctx(self, state: AgentState) -> RunCtx:
        return self.a._ctx[state["rid"]]

    def metered(self, fn):
        """Bind the request's Usage to whatever thread/context the node runs in (token + cost accounting)."""
        def inner(state: AgentState):
            with track_usage(self.ctx(state).usage):
                try:
                    return fn(state)
                except (KeyError, ProviderError):
                    raise  # unknown source id -> 404, upstream model error -> 502 (handled by the API layer)
                except Exception as e:  # a bug in one agent must degrade to an honest message, never a 500 with a stack trace
                    log.exception("agent node %s failed", fn.__name__)
                    route = state.get("route") or "semantic"
                    d = result(route, f"I could not complete this step ({type(e).__name__}). The error has been logged.", limitations=["Internal error while processing the request."])
                    d["abstained"] = False
                    return {"route": route, "draft": d, "verification": {"status": "fail", "issues": ["internal error"]}, "trace": [f"{fn.__name__}: internal error {type(e).__name__}"]}
        inner.__name__ = fn.__name__
        return inner

    # ================================================================== Supervisor
    def supervisor(self, state: AgentState) -> dict:
        c, s = self.ctx(state), self.k.settings
        metas = c.sources(self.k)
        plan = None
        if s.supervisor_mode == "llm" and self.k.llm.available:
            plan = llm_route(self.k.llm, state["question"], metas, s.web_enabled)
        method = "llm" if plan else "rules"
        plan = plan or rules_route(state["question"], metas, c.last, s.web_enabled)
        flags = scan_text(state["question"])
        why = plan.get("why", "")
        return {"route": plan["route"], "term": plan.get("term"), "quoted": plan.get("quoted", False),
                "plan": {"method": method, "why": why, "sub": plan.get("sub"), "question_flags": flags},
                "trace": [f"supervisor: route={plan['route']}{'/' + plan['sub'] if plan.get('sub') else ''} via {method} ({why})"]}

    # ================================================================== shared helpers
    def _stale(self, metas: list[dict], with_warnings: bool = True) -> list[str]:
        out = []
        cur = self.k.embedder.name
        stale = [m["name"] for m in metas if m.get("embedding") != cur]
        if stale:
            out.append(f"Not searchable semantically until re-indexed (embedding model changed): {', '.join(stale)}")
        if with_warnings:
            for m in metas:
                for w in m.get("warnings", []):
                    out.append(f"{m['name']}: {w}")
        return out

    def _no_sources(self, route: str) -> dict:
        return result(route, "There are no indexed sources to search. Upload a file or add a URL first.", limitations=["No sources are indexed in this session."])

    def _generate(self, c: RunCtx, query: str, evidence: list[dict], strict: bool = False) -> tuple[str, bool, list[str]]:
        """-> (answer, llm_generated, limitations). `strict` = verbatim extraction only (used after a failed verification)."""
        llm, lim = self.k.llm, []
        if llm.available and not strict:
            lang = language_name(detect_language(query))
            ev = "\n".join(f"[{e['i']}] " + wrap_untrusted(excerpt(e["context"], 1200), f"{e['source']}, {e['location']}") for e in evidence)
            hist = "".join(f"Earlier question: {t['question'][:200]}\n" for t in c.history[-2:])
            system = f"{ANSWER_SYSTEM} {SYSTEM_GUARD} Answer in {lang}."
            try:
                return llm.complete(system, f"{hist}Question: {query}\n\n{ev}"), True, lim
            except ProviderError as e:
                lim.append(f"LLM unavailable ({e}); showing extracted passages instead.")
        picks = best_sentences(evidence, query)
        body = "\n".join(f"- {sent} [{e['source']}, {e['location']}]" for e, sent in picks)
        if strict:
            lim.append("Answer was regenerated in strict extractive mode after verification flagged the first draft.")
        elif not llm.available:
            lim.append("No LLM configured: passages were extracted, not generated.")
        return "Most relevant passages found in the indexed sources:\n" + body, False, lim

    def _search(self, c: RunCtx, query: str, state: AgentState):
        return self.tools.call("hybrid_search", c, query=query, top_k=c.opts.top_k)

    # ================================================================== Exact Search Agent
    def exact(self, state: AgentState) -> dict:
        c, req = self.ctx(state), self.ctx(state).req
        term = state.get("term")
        if not term:
            return {"draft": result("exact", "Which exact name, ID or phrase should I search for? Please tell me (you can put it in quotes).", needs_input=True, limitations=["No search term was provided."]),
                    "trace": ["exact: no term, asking the user"]}
        metas = c.sources(self.k)
        if not metas:
            return {"draft": self._no_sources("exact")}
        r, _ = self.tools.call("exact_search", c, term=term, case_sensitive=req.case_sensitive, whole_word=req.whole_word)
        cites = [Citation(source_id=m["source_id"], source=m["source"], location=m["location"], excerpt=m["excerpt"], loc=m["loc"]) for m in r.matches]
        lim = [f"Matching rules: {r.rules}."] + self._stale([m for m in metas if m.get("warnings")])[:5]
        if r.truncated:
            lim.append(f"Showing the first {len(r.matches)} of {r.count} matches; the count covers all of them.")
        pages: dict[str, list] = {}
        for m in r.matches:
            if "page" in m["loc"]:
                pages.setdefault(m["source"], [])
                if m["loc"]["page"] not in pages[m["source"]]:
                    pages[m["source"]].append(m["loc"]["page"])
        details = {"term": r.term, "count": r.count, "locations_with_match": r.units_with_match, "by_source": list(r.by_source.values()), "sources_searched": len(metas),
                   "pages": {k: sorted(v) for k, v in pages.items()}}
        if r.count:
            where = "; ".join(f"{v['name']}: {v['count']}" for v in r.by_source.values())
            first = ", ".join(dict.fromkeys(x.location for x in cites[:8]))
            pg = "".join(f" Pages — {k}: {', '.join(map(str, v))}." for k, v in details["pages"].items())
            ans = (f"Found {r.count} occurrence{'s' if r.count != 1 else ''} of “{r.term}” in {r.units_with_match} location{'s' if r.units_with_match != 1 else ''} "
                   f"across {len(r.by_source)} source{'s' if len(r.by_source) != 1 else ''} ({where}). First locations: {first}.{pg}")
            return {"draft": result("exact", ans, confidence="high", citations=cites, limitations=lim, details=details), "trace": [f"exact: {r.count} matches"]}
        ans = f"No occurrences of “{r.term}” were found in the full extracted text of {len(metas)} indexed source{'s' if len(metas) != 1 else ''}."
        d = result("exact", ans, confidence="high", limitations=lim + ["A zero count only covers text that could be extracted (scanned pages need OCR)."], details=details)
        if not state.get("quoted") and len(term.split()) > 1:  # conceptual phrase, e.g. "termination clause": offer related passages
            rr = self._search(c, term, state)
            if rr.hits:
                d["answer"] += " The closest related passages are listed as citations."
                d["citations"] = evidence_citations([hit_to_evidence(i, h) for i, h in enumerate(rr.hits, 1)])
                d["confidence"], d["route"] = "medium", "exact+semantic"
        return {"draft": d, "trace": ["exact: 0 matches"]}

    # ================================================================== Semantic Retrieval Agent
    def semantic(self, state: AgentState) -> dict:
        c = self.ctx(state)
        metas = c.sources(self.k)
        if not metas:
            return {"draft": self._no_sources("semantic")}
        attempt = state.get("attempt", 0)
        if attempt > 0 and state.get("evidence"):
            evidence, rd = state["evidence"], state["draft"].get("details", {}).get("retrieval", {})
            strict, grade, abstained = True, rd.get("grade", "ambiguous"), False
        else:
            res = self._search(c, state["query"], state)
            evidence = [hit_to_evidence(i, h) for i, h in enumerate(res.hits, 1)]
            strict, grade, abstained = False, res.grade, res.abstain
            rd = {"grade": res.grade, "attempts": res.attempts, "query": res.query, "excluded_suspicious": res.excluded_suspicious, "trace": res.trace}
        if abstained or not evidence:
            d = result("semantic", NOT_VERIFIED + " No passage was relevant enough to the question.", limitations=self._stale(metas), details={"retrieval": rd})
            d["abstained"] = True
            return {"draft": d, "evidence": [], "trace": [f"semantic: abstain after {rd.get('attempts', 1)} retrieval attempt(s)"]}
        ans, generated, lim = self._generate(c, state["query"], evidence, strict)
        if rd.get("excluded_suspicious"):
            lim.append(f"{rd['excluded_suspicious']} passage(s) that look like prompt-injection were withheld from the model.")
        d = result("semantic", ans, confidence=confidence_from(evidence, grade), citations=evidence_citations(evidence), limitations=lim + self._stale(metas)[:5], details={"retrieval": rd})
        d["generated"] = generated
        return {"draft": d, "evidence": evidence, "trace": [f"semantic: {len(evidence)} passages, grade={grade}, {'llm' if generated else 'extractive'} answer"]}

    # ================================================================== Document Search Agent
    def document_search(self, state: AgentState) -> dict:
        c, req = self.ctx(state), self.ctx(state).req
        metas = c.sources(self.k)
        if not metas:
            return {"draft": self._no_sources("document_search")}
        term, q = state.get("term"), state["question"]
        if term:  # exact + semantic ("where does clause 8 appear?")
            ex, _ = self.tools.call("exact_search", c, term=term, case_sensitive=req.case_sensitive, whole_word=req.whole_word)
            cites = [Citation(source_id=m["source_id"], source=m["source"], location=m["location"], excerpt=m["excerpt"], loc=m["loc"]) for m in ex.matches]
            rr = self._search(c, state["query"], state)
            sem = evidence_citations([hit_to_evidence(i, h) for i, h in enumerate(rr.hits, 1)])
            seen = {(x.source_id, x.location) for x in cites}
            extra = [x for x in sem if (x["source_id"], x["location"]) not in seen]
            lim = [f"Exact matching rules: {ex.rules}."]
            details = {"term": term, "count": ex.count, "by_source": list(ex.by_source.values())}
            if ex.count:
                locs = ", ".join(dict.fromkeys(x.location for x in cites[:8]))
                ans = f"“{term}” appears {ex.count} time{'s' if ex.count != 1 else ''}: {locs}. Related passages (semantic matches) are also cited."
                return {"draft": result("document_search", ans, confidence="high", citations=cites + extra[:3], limitations=lim, details=details), "trace": [f"document_search: {ex.count} exact + {len(extra)} semantic"]}
            if extra:
                return {"draft": result("document_search", f"The exact phrase “{term}” was not found, but these passages look related (semantic matches). Please verify them.", confidence="low", citations=extra, limitations=lim, details=details)}
            d = result("document_search", f"“{term}” was not found and nothing related could be verified in the indexed sources.", confidence="none", verified=False, limitations=lim, details=details)
            d["abstained"] = True
            return {"draft": d}
        if re.search(r"\b(do i have|have i|uploaded|indexed|available|are there)\b", q, re.I) and not re.search(r"\bmention|contain|discuss|talk|cover|include|reference\b", q, re.I):
            rows = [f"- {m['name']} ({m['kind']}{', ' + str(m['pages']) + ' pages' if m.get('pages') else ''}, {m.get('chunks', '?')} chunks)" for m in metas]
            return {"draft": result("document_search", f"{len(metas)} document(s) available:\n" + "\n".join(rows), confidence="high", details={"documents": [m["name"] for m in metas]}, limitations=[]), "trace": ["document_search: listing"]}
        topic = re.split(r"\b(?:mention(?:s|ed)?|contain(?:s)?|discuss(?:es)?|talk(?:s)? about|cover(?:s)?|include(?:s)?|reference(?:s)?)\b", q, maxsplit=1, flags=re.I)[-1].strip(" ?.!") or q
        res = self._search(c, topic, state)
        if not res.hits:
            d = result("document_search", NOT_VERIFIED + " No document appears to discuss this.", limitations=self._stale(metas), details={"retrieval": {"grade": res.grade, "trace": res.trace}})
            d["abstained"] = True
            return {"draft": d}
        by_doc: dict[str, list] = {}
        for h in res.hits:
            by_doc.setdefault(h.source, []).append(h)
        lines = [f"- {name}: {', '.join(dict.fromkeys(h.location for h in hs))}" for name, hs in by_doc.items()]
        ev = [hit_to_evidence(i, h) for i, h in enumerate(res.hits, 1)]
        d = result("document_search", f"{len(by_doc)} document(s) relevant to “{topic}”:\n" + "\n".join(lines), confidence=confidence_from(ev, res.grade), citations=evidence_citations(ev),
                   limitations=self._stale(metas)[:5], details={"documents": list(by_doc), "retrieval": {"grade": res.grade, "trace": res.trace}})
        return {"draft": d, "evidence": ev, "trace": [f"document_search: {len(by_doc)} documents"]}

    # ================================================================== Web Agent
    def web(self, state: AgentState) -> dict:
        c, s = self.ctx(state), self.k.settings
        q = state["question"]
        urls = list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(q)))[:3]
        lim: list[str] = ["External web content: not part of your indexed documents."]
        pages: list[tuple[str, str, list]] = []  # (url, title, units)
        if not urls:
            try:
                found = web_search.search(s, URL.sub("", q), 4, self.k.url_transport)
            except ProviderError as e:
                return {"draft": result("web", f"Web search is unavailable: {e}", limitations=["Configure MKA_WEB_SEARCH_PROVIDER to enable web search."]), "trace": ["web: no provider"]}
            urls = [f["url"] for f in found][:3]
            lim.append("Pages were found through the configured search provider.")
        for u in urls:
            try:
                final, ex = self.tools.call("fetch_url", c, url=u)
                pages.append((final, ex.title or final, ex.units))
            except (IngestError, ToolError) as e:
                lim.append(f"Could not read {u}: {e}")
        if not pages:
            return {"draft": result("web", NOT_VERIFIED + " No web page could be read.", limitations=lim), "trace": ["web: nothing fetched"]}
        query = URL.sub("", q).strip() or q
        paras, meta = [], []
        for final, title, units in pages:
            for u in units[:400]:
                paras.append(u.text)
                meta.append((final, title, u.loc))
        qv = self.k.embedder.embed_query(query)
        sims = self.k.embedder.embed_documents(paras) @ qv
        from ..core import stem, tokenize

        qs = {stem(t) for t in tokenize(query)}
        scored = sorted(range(len(paras)), key=lambda i: -(float(sims[i]) + 0.5 * len(qs & {stem(t) for t in tokenize(paras[i])}) / max(len(qs), 1)))[:5]
        evidence, flagged = [], 0
        for i in scored:
            sus = bool(scan_text(paras[i]))
            flagged += sus
            if sus and s.injection_policy == "exclude":
                continue
            final, title, loc = meta[i]
            evidence.append({"i": len(evidence) + 1, "chunk_id": f"web:{i}", "source_id": "web", "source": final, "location": format_loc(loc) if loc else final, "text": paras[i],
                             "context": paras[i], "score": round(float(sims[i]), 4), "lexical": 0.0, "suspicious": sus, "rerank": None})
        if not evidence:
            return {"draft": result("web", NOT_VERIFIED, limitations=lim)}
        if flagged:
            lim.append(f"{flagged} web passage(s) looked like prompt-injection and are treated strictly as data.")
        ans, generated, l2 = self._generate(c, query, evidence, bool(state.get("attempt")))
        d = result("web", ans, confidence="medium", citations=evidence_citations(evidence), limitations=lim + l2, details={"urls": [p[0] for p in pages]})
        d["generated"] = generated
        return {"draft": d, "evidence": evidence, "route": "web", "plan": {**state.get("plan", {}), "web_tried": True}, "trace": [f"web: {len(pages)} page(s), {len(evidence)} passages"]}

    # ================================================================== SQL / Pandas Agent
    def data(self, state: AgentState) -> dict:
        c = self.ctx(state)
        metas = [m for m in c.sources(self.k) if m.get("tabular")]
        if not metas:
            return {"draft": result("data", "No CSV/Excel sources are indexed for this question.", limitations=["Upload a .csv or .xlsx file."])}
        try:
            out = self.tools.call("table_query", c, question=state["question"])
        except tab.NotTabular:  # "how many days of leave..." matched aggregate keywords but is not about the spreadsheets
            return {"route": "semantic", "trace": ["data: question is not about the table data -> handing over to the semantic agent"], "plan": {**state.get("plan", {}), "redirected_from": "data"}}
        except (tab.PlanError, ToolError) as e:
            msg = str(e)
            return {"draft": result("data", f"I could not run a reliable calculation: {msg}", needs_input=True,
                                    limitations=["Table questions are executed with a fixed set of operations (count, sum, mean, median, min, max, sort, filter, group, duplicates, compare)."]),
                    "trace": [f"data: clarification needed ({msg[:60]})"]}
        return {"draft": self._data_answer(out), "trace": [f"data: {out['plan']['op']} → {out['kind']}"]}

    def _data_answer(self, out: dict) -> dict:
        from .data_answers import format_data_answer

        return format_data_answer(out)

    # ================================================================== Summarization Agent (summaries, comparison, document intelligence)
    def summarize(self, state: AgentState) -> dict:
        from .summarize import run_summarize

        return run_summarize(self, state)

    # ================================================================== Verification Agent
    def verify(self, state: AgentState) -> dict:
        d, ev, attempt = dict(state.get("draft") or {}), state.get("evidence") or [], state.get("attempt", 0)
        max_retries = self.ctx(state).opts.max_retries
        issues: list[str] = []
        blocking: list[str] = []
        ev_text = "\n".join(e["context"] for e in ev) + "\n" + "\n".join(c["excerpt"] for c in d.get("citations", []))
        answer = d.get("answer", "")
        safe, gi = guard_output(answer, answer if d.get("skip_verify") else ev_text)  # whole-document summaries have no retrieved evidence to check URLs against
        if gi:
            issues += gi
            d["answer"] = answer = safe
        if d.get("generated") and ev:
            markers = {int(m) for m in re.findall(r"\[(\d{1,2})\]", answer)}
            if not markers:
                blocking.append("uncited: the generated answer carries no [n] citation markers")
            elif any(m < 1 or m > len(ev) for m in markers):
                blocking.append("invalid citation marker")
            nums = {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", re.sub(r"\[\d{1,2}\]", "", answer))}
            src_nums = {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", ev_text)}
            missing = sorted(n for n in nums if n not in src_nums)
            if missing:
                blocking.append(f"numbers not present in the evidence: {', '.join(missing[:5])}")
            ratio = support_ratio(re.sub(r"\[\d{1,2}\]", "", answer), ev_text)
            d.setdefault("details", {})["support_ratio"] = round(ratio, 3)
            if ratio < 0.5:
                blocking.append(f"low lexical support ({ratio:.2f})")
            if self.k.llm.available and not blocking:
                j = self._judge(answer, ev)
                if j is False:
                    blocking.append("LLM judge: answer contains unsupported claims")
        status = "pass"
        if blocking:
            status = "retry" if attempt < max_retries else "fail"
        out: dict = {"verification": {"status": status, "issues": issues + blocking}, "attempt": attempt + (1 if status == "retry" else 0),
                     "trace": [f"verify: {status}" + (f" ({'; '.join(blocking)[:120]})" if blocking else "")]}
        if status == "fail":  # retries exhausted: fall back to verbatim evidence rather than shipping an unverified answer
            c = self.ctx(state)
            ans, _, lim = self._generate(c, state["query"], ev, strict=True)
            d.update(answer=ans, generated=False, confidence="low")
            d["limitations"] = list(d.get("limitations", [])) + lim + ["The generated answer failed verification and was replaced by verbatim passages."]
        elif issues:
            d["limitations"] = list(d.get("limitations", [])) + [f"Output filter: {i}" for i in issues]
        out["draft"] = d
        return out

    def _judge(self, answer: str, ev: list[dict]) -> Optional[bool]:
        from ..rag.steps import parse_json

        sys = (f'You check whether an answer is fully supported by the evidence. JSON only: {{"supported": true|false}}. {SYSTEM_GUARD}')
        body = "\n".join(f"[{e['i']}] " + wrap_untrusted(excerpt(e["context"], 800), e["source"]) for e in ev)
        try:
            j = parse_json(self.k.llm.complete(sys, f"Answer: {answer}\n\n{body}"))
        except ProviderError:
            return None
        return j.get("supported") if isinstance(j, dict) and isinstance(j.get("supported"), bool) else None

    # ================================================================== Final Response Agent
    def final(self, state: AgentState) -> dict:
        from .followups import suggest_followups

        c = self.ctx(state)
        d = dict(state["draft"])
        d.pop("generated", None)
        d.pop("skip_verify", None)
        abstained = d.pop("abstained", False)
        ver = state.get("verification") or {}
        det = d.setdefault("details", {})
        det["plan"] = state.get("plan", {})
        det["verification"] = ver
        det["trace"] = state.get("trace", [])
        d["followups"] = suggest_followups(self.k, c, state, d)
        d["language"] = detect_language(state["question"])
        if abstained:
            d["verified"], d["confidence"] = False, "none"
        if det.get("plan", {}).get("question_flags"):
            d.setdefault("limitations", []).append("The question contained text that resembles a prompt-injection attempt; it was treated as plain data.")
        return {"result": d, "trace": ["final: assembled response"]}


def support_ratio(answer: str, evidence: str) -> float:
    from ..core import stem, tokenize

    a = [stem(t) for t in tokenize(answer) if not t.isdigit()]
    if not a:
        return 1.0
    e = {stem(t) for t in tokenize(evidence)}
    return sum(1 for t in a if t in e) / len(a)
