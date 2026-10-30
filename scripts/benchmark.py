"""Measures what this deployment can do on large inputs and writes docs/perf.json (rendered into docs/PERFORMANCE.md and the BRD).
Offline configuration (hash embedder, local vector store, SQLite, no LLM): numbers are for THIS machine; re-run on yours.
    python scripts/benchmark.py [--pages 1000] [--rows 200000] [--out docs/perf.json]"""
from __future__ import annotations

import argparse
import io
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.agents import Assistant  # noqa: E402
from app.analytics import insights, sqlbox  # noqa: E402
from app.config import Settings  # noqa: E402
from app.reports.build import build  # noqa: E402
from app.reports.render import render  # noqa: E402
from app.schemas import AskRequest  # noqa: E402
from app.security.auth import ANONYMOUS  # noqa: E402
from app.service import Knowledge  # noqa: E402
from app.storage import Scope  # noqa: E402
from app.tools import tabular as tab  # noqa: E402
from app.tools.exact import exact_search  # noqa: E402

WORDS = "policy employee leave annual review budget invoice customer contract security incident approval travel expense manager report quarter forecast supplier delivery".split()


def make_pdf(pages: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for p in range(1, pages + 1):
        y = 800
        for ln in range(45):
            line = " ".join(WORDS[(p * 7 + ln * 3 + i) % len(WORDS)] for i in range(12))
            if p % 40 == 0 and ln == 3:
                line = f"Contact Anjali Rao about item {p}. " + line
            c.drawString(40, y, line[:110])
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def timed(fn, n=1):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return out, ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--rows", type=int, default=200_000)
    ap.add_argument("--out", default=str(root / "docs" / "perf.json"))
    a = ap.parse_args()
    td = Path(tempfile.mkdtemp(prefix="mka-bench-"))
    res: dict = {"machine": {"python": platform.python_version(), "platform": platform.platform(), "cpus": __import__("os").cpu_count()}, "config": "hash embedder, local vector store, SQLite, no LLM", "pages": a.pages, "rows": a.rows}
    k = Knowledge(Settings(data_dir=str(td / "d"), max_pdf_pages=max(a.pages, 5000), _env_file=None))
    asst, scope = Assistant(k), Scope("bench", "w")

    # ---- large PDF
    pdf = td / "big.pdf"
    t0 = time.perf_counter()
    pdf.write_bytes(make_pdf(a.pages))
    res["pdf"] = {"mb": round(pdf.stat().st_size / 1e6, 2), "generate_s": round(time.perf_counter() - t0, 1)}
    r, ts = timed(lambda: k.ingest_file(scope, pdf, "big.pdf"))
    assert r["status"] == "ready", r
    meta = r["source"]
    res["pdf"].update(ingest_s=round(ts[0] / 1000, 1), pages_per_s=round(a.pages / (ts[0] / 1000), 1), chunks=meta["chunks"], peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
    st = k.store(scope)
    ids = [meta["id"]]
    _, ex = timed(lambda: exact_search(st.iter_units(ids), "Anjali Rao", max_excerpts=50), 5)
    count = exact_search(st.iter_units(ids), "Anjali Rao", max_excerpts=5).count
    res["exact_search"] = {"term_count": count, "expected": a.pages // 40, "ms_p50": round(statistics.median(ex)), "ms_max": round(max(ex))}
    qs = ["annual leave approval policy", "supplier delivery forecast", "security incident report", "travel expense manager", "customer contract invoice"]
    from app.rag import resolve

    opts = resolve(k.settings)
    _, rt = timed(lambda: [asst.pipeline.retrieve(st, q, opts, ids) for q in qs], 3)
    per = [t / len(qs) for t in rt]
    res["hybrid_retrieval_ms"] = {"p50": round(statistics.median(per)), "p95": round(pct(per, 95)), "note": "includes first-query index load for the first run"}
    _, at = timed(lambda: [asst.ask(scope, AskRequest(question=q), ANONYMOUS, conversation_id="b") for q in qs], 3)
    per = [t / len(qs) for t in at]
    res["ask_end_to_end_ms"] = {"p50": round(statistics.median(per)), "p95": round(pct(per, 95))}
    _, sm = timed(lambda: build("summary", k, asst, scope, ANONYMOUS, ids, {"style": "short"}))
    doc, _ = timed(lambda: build("summary", k, asst, scope, ANONYMOUS, ids, {"style": "short"}))
    res["summary_report_s"] = {"build": round(sm[0] / 1000, 1)}
    for fmt in ("pdf", "docx", "xlsx"):
        _, t = timed(lambda f=fmt: render(doc, f))
        res["summary_report_s"][fmt] = round(t[0] / 1000, 2)

    # ---- large spreadsheet
    csv = td / "rows.csv"
    lines = ["OrderID,Date,Region,Product,Revenue"]
    regions = ["North", "South", "East", "West"]
    for i in range(a.rows):
        lines.append(f"{i},{2022 + (i // 6000) % 3}-{(i // 500) % 12 + 1:02d}-{i % 27 + 1:02d},{regions[i % 4]},P{i % 50},{(i * 37) % 997 + 10}")
    csv.write_text("\n".join(lines))
    res["csv"] = {"mb": round(csv.stat().st_size / 1e6, 1)}
    r, ts = timed(lambda: k.ingest_file(scope, csv, "rows.csv"))
    assert r["status"] == "ready", r
    sid = r["source"]["id"]
    res["csv"].update(ingest_s=round(ts[0] / 1000, 1), rows_per_s=round(a.rows / (ts[0] / 1000)))
    tables, tl = timed(lambda: tab.load_tables(st, [st.get_source(sid)]))
    t = tables[0]
    res["csv"]["load_tables_cold_ms"] = round(tl[0])
    res["csv"]["load_tables_warm_ms"] = round(timed(lambda: tab.load_tables(st, [st.get_source(sid)]))[1][0], 1)
    _, pt = timed(lambda: insights.profile(t))
    res["csv"]["profile_ms"] = round(pt[0])
    _, tt = timed(lambda: insights.trend(t, "Date", "Revenue", "M"))
    res["csv"]["trend_ms"] = round(tt[0])
    _, an = timed(lambda: insights.anomalies(t, "Revenue"))
    res["csv"]["anomalies_ms"] = round(an[0])
    sb = sqlbox.build(tables)
    res["csv"]["sql_sandbox_build_ms"] = round(timed(lambda: sqlbox.build(tables))[1][0])
    _, sq = timed(lambda: sqlbox.run(sb, "SELECT region, SUM(revenue) AS total, COUNT(*) n FROM rows GROUP BY region ORDER BY total DESC"), 3)
    res["csv"]["sql_group_by_ms"] = round(statistics.median(sq))
    _, pl = timed(lambda: tab.analyse(tables, "Which region has the highest total revenue?"))
    res["csv"]["pandas_question_ms"] = round(pl[0])
    res["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
