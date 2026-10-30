"""Content builders: turn a request into a report Doc. Everything is computed from the caller's accessible sources only."""
from __future__ import annotations

from ..analytics import charts, insights, sqlbox
from ..core import format_loc
from ..intel import compare as cmp
from ..intel import contradict as contra
from ..intel.summaries import summarize_source
from ..schemas import AskRequest
from ..tools import tabular as tab
from ..tools.exact import exact_search
from .model import Doc

KINDS = ("summary", "executive", "comparison", "research", "analytics", "exact_search")
MAX_SOURCES = 20
MAX_QUESTIONS = 10


class ReportError(ValueError):
    """Bad request (unknown source, wrong kind of source, ...). The message is shown to the user."""


def _sources(k, st, principal, ids: list[str] | None, need: int = 1, tabular: bool | None = None) -> list[dict]:
    metas = st.list_sources(principal)
    if ids:
        by = {m["id"]: m for m in metas}
        missing = [i for i in ids if i not in by]
        if missing:
            raise ReportError("Unknown or inaccessible source id(s): " + ", ".join(missing))
        metas = [by[i] for i in ids]
    if tabular is True:
        metas = [m for m in metas if m.get("tabular")]
    elif tabular is False:
        metas = [m for m in metas if not m.get("tabular")]
    if len(metas) < need:
        raise ReportError(f"This report needs at least {need} {'spreadsheet' if tabular else 'document'}(s).")
    return metas[:MAX_SOURCES]


def summary_report(k, st, principal, ids, style: str = "detailed", section: str | None = None, **_) -> Doc:
    metas = _sources(k, st, principal, ids)
    doc = Doc(f"{'Executive summary' if style == 'executive' else 'Summary report'}", subtitle=f"Style: {style}")
    for m in metas:
        try:
            s = summarize_source(k, st, m, style, section)
        except (ValueError, LookupError) as e:
            raise ReportError(str(e)) from e
        doc.h(s["source"], 1)
        doc.note(f"{m['kind'].upper()} · version {m.get('version', 1)} · {m.get('pages') or m.get('units') or '?'} {'pages' if m.get('pages') else 'units'} · method: {s['method']}")
        if s["sections"]:
            for sec in s["sections"]:
                doc.h(sec["title"] + (f"  (pages {sec['pages'][0]}-{sec['pages'][1]})" if sec["pages"] and sec["pages"][0] != sec["pages"][1] else ""), 2)
                doc.p(sec["summary"])
        else:
            doc.p(s["summary"])
            if s.get("figures"):
                doc.h("Key figures", 2).bullets(s["figures"])
    doc.add_sources(metas)
    doc.note("Summaries cover the complete text of each document. " + ("They were written by a language model from that text." if k.llm.available else "No language model is configured: summaries are extractive (key sentences)."))
    return doc


def comparison_report(k, st, principal, ids, mode: str = "diff", **_) -> Doc:
    metas = _sources(k, st, principal, ids, need=2, tabular=False)
    if len(metas) != 2 and mode == "diff":
        raise ReportError("A document comparison needs exactly two documents.")
    doc = Doc("Comparison report", subtitle=" vs ".join(m["name"] for m in metas[:4]))
    if mode == "diff":
        a, b = metas[0], metas[1]
        d = cmp.compare_units([u for _, u in st.iter_units([a["id"]])], [u for _, u in st.iter_units([b["id"]])])
        s = d["summary"]
        doc.h("Overview").table(["Measure", "Count"], [["Sentences compared (A / B)", f"{s['segments_a']} / {s['segments_b']}"], ["Unchanged", s["unchanged"]], ["Changed", s["changed"]], ["Added in B", s["added"]], ["Removed from A", s["removed"]], ["Similarity", f"{s['similarity']:.1%}"]])
        if d["changed"]:
            doc.h("Changed passages").table(["Before", "Where", "After", "Where", "Numbers"], [[c["before"]["text"][:300], format_loc(c["before"]["loc"]), c["after"]["text"][:300], format_loc(c["after"]["loc"]),
                                                                                           ", ".join(f"{x['from']}→{x['to']}" for x in c["number_changes"])] for c in d["changed"]])
        if d["added"]:
            doc.h(f"Only in {b['name']}").table(["Passage", "Where"], [[x["text"][:400], format_loc(x["loc"])] for x in d["added"]])
        if d["removed"]:
            doc.h(f"Only in {a['name']}").table(["Passage", "Where"], [[x["text"][:400], format_loc(x["loc"])] for x in d["removed"]])
        if d["truncated"]:
            doc.note(f"Only the first {cmp.MAX_SEGMENTS} sentences of each document were compared.")
    else:
        passages = []
        for m in metas:
            for _, u in st.iter_units([m["id"]]):
                from ..agents.common import split_sentences

                passages += [{"source_id": m["id"], "source": m["name"], "loc": u.loc, "text": s} for s in split_sentences(u.text) if len(s) >= 25][:3000]
        res = contra.find(passages, k.llm if k.llm.available else None)
        doc.h("Contradictions" if res["method"] == "llm" else "Candidate contradictions (heuristic)")
        doc.note("Each pair was judged by the language model." if res["method"] == "llm" else "Heuristic detector (numbers, negation, antonyms): review each pair; configure an LLM for judged results.")
        doc.table(["Type", "Source A", "Where", "Passage A", "Source B", "Where", "Passage B"], [[c["type"], c["a"]["source"], format_loc(c["a"]["loc"]), c["a"]["text"][:250], c["b"]["source"], format_loc(c["b"]["loc"]), c["b"]["text"][:250]]
                                                                                            for c in res["contradictions"]]) if res["contradictions"] else doc.p("No contradictions were found.")
    doc.add_sources(metas)
    return doc


def exact_report(k, st, principal, ids, term: str = "", case_sensitive: bool = False, whole_word: bool = True, **_) -> Doc:
    if not term.strip():
        raise ReportError("exact_search report needs a 'term'")
    metas = _sources(k, st, principal, ids)
    r = exact_search(st.iter_units([m["id"] for m in metas]), term, case_sensitive=case_sensitive, whole_word=whole_word, max_excerpts=2000)
    doc = Doc(f"Exact search report: “{r.term}”", subtitle=r.rules)
    doc.h("Totals").table(["Document", "Occurrences"], [[v["name"], v["count"]] for v in r.by_source.values()] + [["TOTAL", r.count]])
    pages: dict[str, list] = {}
    for m in r.matches:
        if "page" in m["loc"]:
            pages.setdefault(m["source"], [])
            if m["loc"]["page"] not in pages[m["source"]]:
                pages[m["source"]].append(m["loc"]["page"])
    if pages:
        doc.h("Pages with a match").table(["Document", "Pages"], [[n, ", ".join(map(str, sorted(p)))] for n, p in pages.items()])
    if r.matches:
        doc.h("Matches").table(["Document", "Where", "Context"], [[m["source"], m["location"], m["excerpt"]] for m in r.matches])
    if r.truncated:
        doc.note("The list shows the first 2000 matches; the totals above count all of them.")
    doc.add_sources(metas)
    return doc


def analytics_report(k, st, principal, ids, sheet: str | None = None, date_column: str | None = None, value_column: str | None = None, queries: list[str] | None = None, **_) -> Doc:
    metas = _sources(k, st, principal, ids, tabular=True)
    tables = tab.load_tables(st, metas)
    if sheet is not None:
        tables = [t for t in tables if t.sheet == sheet]
    if not tables:
        raise ReportError("No matching table found")
    doc = Doc("Data analysis report", subtitle=", ".join(m["name"] for m in metas))
    for t in tables[:8]:
        label = t.source + (f" / {t.sheet}" if t.sheet else "")
        pr = insights.profile(t)
        doc.h(label, 1).h("Profile", 2)
        doc.table(["Column", "Type", "Missing", "Distinct", "Min", "Max", "Mean"], [[c["name"], c["type"], f"{c['missing']} ({c['missing_pct']}%)", c["unique"], c.get("min", ""), c.get("max", ""), c.get("mean", "")] for c in pr["columns"]],
                  caption=f"{pr['rows']} rows · {pr['duplicate_rows']} duplicate row(s)")
        for col in t.numeric[:4]:
            a = insights.anomalies(t, col)
            if a["count"]:
                doc.h(f"Outliers in {col}", 3).table(["Row", "Value", "Score"], [[r["row"], r["value"], r["score"]] for r in a["rows"][:15]], caption=f"{a['method'].upper()} rule, normal range {a['bounds']['low']:.4g} to {a['bounds']['high']:.4g}")
        dates = insights.date_columns(t)
        dcol = date_column if date_column in dates else (next(iter(dates), None))
        vcol = value_column if value_column in t.numeric else (t.numeric[0] if t.numeric else None)
        if dcol and vcol:
            tr = insights.clean(insights.trend(t, dcol, vcol))
            doc.h(f"{vcol} by {tr['freq_name']}", 2).chart(charts.from_result({"kind": "trend", "trend": tr}))
            doc.table(["Period", "Value", "Change %"], [[p["period"], p["value"], p["change_pct"] if p["change_pct"] is not None else ""] for p in tr["periods"]],
                      caption=f"Direction: {tr['direction']} · peak {tr['best']['period']} · low {tr['worst']['period']}")
    if queries:
        sb = sqlbox.build(tables)
        try:
            for q in queries[:5]:
                try:
                    res = sqlbox.run(sb, q, max_rows=200)
                except sqlbox.SqlError as e:
                    raise ReportError(f"Query rejected: {e}") from e
                doc.h("Query", 2).p(res["sql"]).table(res["columns"], res["rows"], caption=f"{res['row_count']} row(s)" + (" (truncated)" if res["truncated"] else ""))
        finally:
            sb.conn.close()
    doc.add_sources(metas)
    doc.note("Figures are computed with pandas / read-only SQL over every row of the uploaded sheets. Row numbers are spreadsheet rows (header = row 1).")
    return doc


def research_report(k, assistant, scope, principal, ids, questions: list[str] | None = None, title: str | None = None, **_) -> Doc:
    qs = [q.strip() for q in (questions or []) if q and q.strip()][:MAX_QUESTIONS]
    if not qs:
        raise ReportError("research report needs at least one question")
    st = k.store(scope)
    metas = _sources(k, st, principal, ids)
    doc = Doc(title or "Research report", subtitle=f"{len(qs)} question(s) answered from {len(metas)} document(s)")
    index = []
    for i, q in enumerate(qs, 1):
        r = assistant.ask(scope, AskRequest(question=q, source_ids=[m["id"] for m in metas]), principal, conversation_id=f"report-{i}")
        index.append([i, q, r.route, r.confidence, "yes" if r.verified else "no"])
        doc.h(f"{i}. {q}", 1).p(r.answer)
        web = [c for c in r.citations if c.origin == "web"]
        docs = [c for c in r.citations if c.origin != "web"]
        if docs:
            doc.h("Evidence from your documents", 3).table(["Source", "Where", "Excerpt"], [[c.source, c.location, c.excerpt] for c in docs])
        if web:
            doc.h("External web evidence (not from your documents)", 3).table(["Page", "Excerpt"], [[c.source, c.excerpt] for c in web])
        if r.limitations:
            doc.note("Limitations: " + " ".join(r.limitations))
    doc.blocks.insert(0, ("table", {"header": ["#", "Question", "Agent", "Confidence", "Verified"], "rows": index, "caption": "Overview"}))
    doc.add_sources(metas)
    return doc


def build(kind: str, k, assistant, scope, principal, ids, params: dict) -> Doc:
    st = k.store(scope)
    if kind in ("summary", "executive"):
        return summary_report(k, st, principal, ids, style="executive" if kind == "executive" else params.get("style", "detailed"), section=params.get("section"))
    if kind == "comparison":
        return comparison_report(k, st, principal, ids, mode=params.get("mode", "diff"))
    if kind == "exact_search":
        return exact_report(k, st, principal, ids, term=params.get("term", ""), case_sensitive=bool(params.get("case_sensitive")), whole_word=params.get("whole_word", True))
    if kind == "analytics":
        return analytics_report(k, st, principal, ids, sheet=params.get("sheet"), date_column=params.get("date_column"), value_column=params.get("value_column"), queries=params.get("queries"))
    if kind == "research":
        return research_report(k, assistant, scope, principal, ids, params.get("questions"), params.get("title"))
    raise ReportError(f"Unknown report kind '{kind}'. Choose one of: {', '.join(KINDS)}")
