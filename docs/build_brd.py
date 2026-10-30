"""Builds docs/Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf (requires reportlab).
Numbers in the evaluation / verification sections are read from docs/eval/eval_report.json and docs/facts.json, not typed by hand."""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
OUT = HERE / "Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf"
rep = json.loads((HERE / "eval" / "eval_report.json").read_text())
ext = json.loads((HERE / "eval" / "eval_report_extended.json").read_text())
perf = json.loads((HERE / "perf.json").read_text())
facts = json.loads((HERE / "facts.json").read_text())
M = rep["metrics"]
X = ext["metrics"]

ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12.4, alignment=TA_LEFT, spaceAfter=4)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.8, leading=10, spaceAfter=0)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8, leading=10, spaceAfter=0)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#1f3a93"), spaceBefore=10, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#243b6b"), spaceBefore=8, spaceAfter=3)
BUL = ParagraphStyle("bul", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=2)
TITLE = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=26, leading=31, textColor=colors.HexColor("#1f3a93"), alignment=TA_LEFT)
ACC = colors.HexColor("#1f3a93")
OKC, WARNC, BADC = colors.HexColor("#1b7f3b"), colors.HexColor("#b45309"), colors.HexColor("#b42318")

p = lambda t, s=BODY: Paragraph(t, s)  # noqa: E731
bullets = lambda items: [Paragraph(i, BUL, bulletText="•") for i in items]  # noqa: E731
pct = lambda v: "n/a" if v is None else f"{100 * v:.1f}%"  # noqa: E731


def table(rows, widths, header=True, status_col=None, zebra=True):
    data = [[Paragraph(str(c), CELLB if (header and i == 0) else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ced8")), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6ebf8"))]
    if zebra:
        st += [("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#f7f8fb")])]
    t.setStyle(TableStyle(st))
    return t


STATUS = {"T": ("Implemented, tested", OKC), "P": ("Implemented, partly tested", WARNC), "N": ("Pending", BADC)}


def status(code: str, note: str = "") -> str:
    label, col = STATUS[code]
    return f'<font color="{col.hexval()}"><b>{label}</b></font>' + (f"<br/>{note}" if note else "")


def flow(width, height, boxes, arrows, font=7.4):
    d = Drawing(width, height)
    for x, y, w, h, text, fill in boxes:
        d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            d.add(String(x + w / 2, y + h / 2 + (len(lines) - 1) * 4.2 - i * 8.4 - 2.5, ln, fontSize=font, fillColor=colors.HexColor("#111827"), textAnchor="middle", fontName="Helvetica-Bold" if i == 0 else "Helvetica"))
    for x1, y1, x2, y2, label in arrows:
        d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.8))
        import math

        a = math.atan2(y2 - y1, x2 - x1)
        d.add(Polygon([x2, y2, x2 - 5 * math.cos(a - 0.4), y2 - 5 * math.sin(a - 0.4), x2 - 5 * math.cos(a + 0.4), y2 - 5 * math.sin(a + 0.4)], fillColor=colors.HexColor("#4a5a8a"), strokeColor=None))
        if label:
            d.add(String((x1 + x2) / 2 + 2, (y1 + y2) / 2 + 3, label, fontSize=6.3, fillColor=colors.HexColor("#374151")))
    return d


def _arrow(d, pts, label=None, dashed=False):
    import math

    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        ln = Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.8)
        if dashed:
            ln.strokeDashArray = [3, 2]
        d.add(ln)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    d.add(Polygon([x2, y2, x2 - 5 * math.cos(ang - 0.4), y2 - 5 * math.sin(ang - 0.4), x2 - 5 * math.cos(ang + 0.4), y2 - 5 * math.sin(ang + 0.4)], fillColor=colors.HexColor("#4a5a8a"), strokeColor=None))
    if label:
        lx, ly = label[1], label[2]
        d.add(String(lx, ly, label[0], fontSize=6.5, fillColor=colors.HexColor("#374151")))


def _box(d, x, y, w, h, title, sub, fill, fs=7.2):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
    d.add(String(x + w / 2, y + h - 10.5, title, fontSize=fs, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
    for i, ln in enumerate(sub.split("\n")):
        d.add(String(x + w / 2, y + h - 19.5 - i * 7.6, ln, fontSize=fs - 0.8, textAnchor="middle", fillColor=colors.HexColor("#111827")))


def system_diagram():
    B, G, O, V = "#e8eefc", "#e5f4ea", "#fdf0dc", "#f1e8fb"
    d = Drawing(520, 250)
    d.add(String(5, 238, "System context - API tier is stateless; state lives in PostgreSQL, Redis, the vector store and the data volume", fontSize=7.8, fillColor=colors.HexColor("#1f3a93"), fontName="Helvetica-Bold"))
    _box(d, 5, 150, 92, 58, "React + TypeScript", "14 screens, light/dark\nSSE streaming, charts\ntoken in memory only", B)
    _box(d, 135, 118, 170, 112, "FastAPI application", "auth - RBAC - tenants - rate limits - audit\nrouters: sources, chat, exact search, summaries,\ncompare, analytics, web, reports, memory,\neval, admin  |  LangGraph agents\n/metrics - OpenTelemetry - request IDs", G)
    _box(d, 345, 178, 80, 38, "PostgreSQL 16", "users, documents+ACL,\njobs, audit, checkpoints", O)
    _box(d, 436, 178, 80, 38, "Redis 7", "queue, rate limits,\nscheduler lock", O)
    _box(d, 345, 128, 80, 38, "Qdrant / Chroma", "vectors (tenant filter\nis mandatory)", O)
    _box(d, 436, 128, 80, 38, "Data volume", "originals, units, chunks,\ntables, graph, reports", O)
    _box(d, 135, 36, 80, 40, "Ingestion worker", "python -m app.worker\nOCR, extract, embed", V)
    _box(d, 225, 36, 80, 40, "Scheduler", "python -m app.scheduler\nretention, housekeeping", V)
    _box(d, 345, 36, 171, 40, "Optional external services", "OpenAI / Gemini - approved web domains - OTLP collector\nPrometheus - LangSmith (env wiring only)", R_)
    _arrow(d, [(97, 180), (135, 180)], ("HTTPS", 100, 184))
    for y in (197, 147):
        _arrow(d, [(305, y), (345, y)])
    _arrow(d, [(305, 160), (436, 160), (436, 166)], None)
    _arrow(d, [(175, 76), (175, 118)])
    _arrow(d, [(265, 76), (265, 118)])
    _arrow(d, [(305, 128), (345, 70)], None, dashed=True)
    return d


R_ = "#fbe7e7"


def agent_diagram():
    B, G, O, R = "#e8eefc", "#e5f4ea", "#fdf0dc", "#fbe7e7"
    d = Drawing(520, 280)
    d.add(String(5, 268, "LangGraph StateGraph - typed, checkpointed state; every node has timeout, retry, metrics and a trace span", fontSize=7.8, fillColor=colors.HexColor("#1f3a93"), fontName="Helvetica-Bold"))
    _box(d, 5, 118, 84, 44, "Supervisor", "rules | LLM tool-call\nintent splitting", B)
    ys = {"exact": 228, "data": 196, "semantic": 164, "doc": 132, "sum": 100, "cmp": 68, "web": 36}
    names = {"exact": ("Exact Search", "regex, full corpus"), "data": ("Data Analyst", "pandas | SQL | charts"), "semantic": ("Document Agent", "advanced RAG + Self-RAG"), "doc": ("Document Search", "exact + semantic"),
             "sum": ("Summary Agent", "short/detailed/executive/chapter"), "cmp": ("Comparison Agent", "diff, versions, contradictions"), "web": ("Web Research", "approved sources only")}
    for k, (t, sub) in names.items():
        _box(d, 122, ys[k], 118, 28, t, sub, G, 7)
    _box(d, 290, 118, 100, 44, "Verification", "numbers, citations vs stored\ntext, judge, widen+retry", O)
    _box(d, 430, 118, 84, 44, "Final Response", "follow-ups, language,\ntrace, usage", B)
    _box(d, 290, 36, 100, 38, "Parallel branches", "Send x N -> agent +\nverification -> Merge", R)
    for k in ys:
        _arrow(d, [(89, 140), (122, ys[k] + 14)])
    for k in ("semantic", "doc", "sum", "cmp", "web"):
        _arrow(d, [(240, ys[k] + 14), (290, 140)])
    _arrow(d, [(390, 140), (430, 140)], ("pass / fail", 392, 145))
    _arrow(d, [(340, 118), (340, 74)], ("compound question", 344, 98), dashed=True)
    _arrow(d, [(240, ys["exact"] + 14), (472, ys["exact"] + 14), (472, 162)])
    _arrow(d, [(240, ys["data"] + 14), (262, ys["data"] + 14), (262, 188), (455, 188), (455, 162)])
    _arrow(d, [(390, 55), (472, 55), (472, 118)])
    d.add(String(5, 6, "semantic -> Web when abstained and fallback is on; data -> Document Agent when the question is not about the tables; verify retry: 1st widened retrieval, then strict extraction", fontSize=6.2, fillColor=colors.HexColor("#374151")))
    return d


def rag_diagram():
    B, G, O = "#e8eefc", "#e5f4ea", "#fdf0dc"
    names = [("Query", "rewrite\n(LLM | merge)", B), ("Variants", "multi-query\nHyDE, x-lingual", B), ("Retrieve", "vector + BM25\nACL + filters", G), ("Fuse", "RRF\n+ graph", G), ("Gate", "relevance\n+ injection", O),
             ("Parents", "parent-child\nde-dupe", G), ("Rerank", "lexical | LLM\ncross-enc.", G), ("Compress", "verbatim\nsentences", G), ("Grade", "correct | weak\n| incorrect", O)]
    d = Drawing(500, 150)
    w, h, gap = 48, 38, 7
    for i, (t, sub, c) in enumerate(names):
        x = 3 + i * (w + gap)
        d.add(Rect(x, 100, w, h, rx=4, ry=4, fillColor=colors.HexColor(c), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
        d.add(String(x + w / 2, 100 + h - 11, t, fontSize=6.8, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
        for j, ln in enumerate(sub.split("\n")):
            d.add(String(x + w / 2, 100 + h - 21 - j * 7.5, ln, fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
        if i:
            _arrow(d, [(x - gap, 119), (x, 119)])
    last = 3 + 8 * (w + gap) + w / 2
    d.add(Rect(60, 44, 200, 26, rx=4, ry=4, fillColor=colors.HexColor("#fbe7e7"), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
    d.add(String(160, 59, "Corrective loop (bounded by MAX_RETRIES)", fontSize=6.8, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
    d.add(String(160, 50, "weak/incorrect -> reformulate or broaden, retry", fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
    _arrow(d, [(last, 100), (last, 57), (260, 57)])
    _arrow(d, [(60, 57), (27, 57), (27, 100)])
    d.add(Rect(290, 8, 210, 40, rx=4, ry=4, fillColor=colors.HexColor("#f1e8fb"), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
    d.add(String(395, 37, "Self-RAG (optional, per request)", fontSize=6.8, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
    d.add(String(395, 28, "retrieve-or-not -> passage relevance -> answer", fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
    d.add(String(395, 20, "-> sentence-level support critique -> bounded regeneration", fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
    d.add(String(395, 12, "-> drop unsupported statements | verbatim fallback", fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
    _arrow(d, [(last, 57), (last, 48), (440, 48)], None, dashed=True)
    return d


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(18 * mm, 10 * mm, "Multi-Agent Knowledge Assistant - Business Requirements Document v2.1 (supersedes v2.0)")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def ms(v):
    return "n/a" if v is None else f"{v:,.0f} ms"


pf, cv = perf["pdf"], perf["csv"]
A, AG = M["answers"], X["agents"]
S: list = []
# ------------------------------------------------------------------ cover
S += [Spacer(1, 38 * mm), p("BUSINESS REQUIREMENTS DOCUMENT", ParagraphStyle("k", parent=BODY, fontSize=10, textColor=colors.HexColor("#6b7280"))), p("Multi-Agent Knowledge Assistant", TITLE),
      p("Enterprise AI Knowledge &amp; Research Platform", ParagraphStyle("st", parent=BODY, fontSize=13, leading=17, textColor=colors.HexColor("#243b6b"))), Spacer(1, 7 * mm),
      p("<b>Version 2.1</b> (supersedes v2.0 of 30 October 2026 and v1.0 of 29 October 2026) &nbsp;|&nbsp; <b>Date:</b> 30 October 2026"),
      p("<b>Technology:</b> Python 3.12, FastAPI, LangGraph, SQLAlchemy + Alembic, PyMuPDF, pandas, PostgreSQL 16, Redis 7, Qdrant / ChromaDB, OpenAI / Gemini (optional), React + TypeScript, Prometheus, OpenTelemetry"), Spacer(1, 5 * mm),
      table([["Purpose", "Define goals, users, scope, requirements, architecture, security, evaluation and acceptance criteria of the platform, and record - requirement by requirement - what is implemented, how it was verified and what is not."],
             ["Status labels", f'{status("T")}: implemented and covered by automated tests that were executed. {status("P")}: implemented, but a dependency (live LLM API, model download, container runtime, external server) was not available in the verification environment, so only the stated part was tested. {status("N")}: not implemented.'],
             ["What changed in v2.1", "Alembic migrations and a PostgreSQL document registry (versions, ACL); PyMuPDF engine, XLS/HTML, duplicate detection and versioning; classification, timeline, page previews; data-analyst toolkit with a sandboxed SQL engine and charts; Comparison Agent, contradiction detection, Self-RAG, citation validation; parallel agents, timeouts, metrics, tracing, retention scheduler; reports in PDF/DOCX/XLSX; user-controlled memory; refresh tokens and roles user/manager/admin; full 14-screen UI; extended evaluation and performance measurements."]],
            [30, 140], header=False, zebra=False),
      Spacer(1, 5 * mm), p("<b>Revision history</b>"), table([["Version", "Date", "Change"], ["1.0", "29 Oct 2026", "Initial BRD: multi-format ingestion, hybrid search, exact counts, table analysis, LangGraph routing."],
                                                              ["2.0", "30 Oct 2026", "Multi-tenant auth and RBAC, PostgreSQL/Qdrant/Redis, background workers, advanced RAG, 8-agent graph with verification, evaluation harness, React dashboard, Docker/CI."],
                                                              ["2.1", "30 Oct 2026", "Enterprise research platform upgrade (this document). Requirements are traced to code and tests in docs/REQUIREMENTS_TRACE.md."]], [16, 24, 130]),
      PageBreak()]

# ------------------------------------------------------------------ 1 executive summary + verification
S += [p("1. Executive Summary", H1),
      p("The platform lets people upload large, mixed-format document collections (or point at approved web pages), ask questions in natural language and receive answers backed by verifiable evidence - file, version, page, sheet and row, section or URL. "
        "Version 2.1 adds what an enterprise research workflow needs on top of v2.0: a document registry with versions and sharing, deeper ingestion (PyMuPDF, XLS, HTML, duplicates, classification, timelines), a data-analyst toolkit with a sandboxed SQL engine, "
        "document comparison with change and contradiction detection, a Self-RAG loop and citation validation, parallel multi-agent answers, report generation in PDF/DOCX/XLSX, user-controlled memory, retention and observability."),
      p("<b>Design principles</b>")] + bullets([
    "<b>Evidence or abstention.</b> Answers cite their sources; every citation is re-checked against the stored text (page/row exists, excerpt is there). Insufficient evidence yields an explicit 'could not verify'.",
    "<b>Code computes, models explain.</b> Counts and figures come from deterministic code (pandas, a read-only SQL sandbox) over the complete data. No generated code or SQL is ever executed outside the sandbox's authorizer.",
    "<b>Documents are data, never instructions.</b> Retrieved text is fenced and scanned; the tool set is closed; HyDE text is never evidence; web evidence is kept apart from document evidence.",
    "<b>Isolation by construction.</b> Tenant, workspace and document ACL are enforced below the API layer; hidden documents are indistinguishable from missing ones.",
    "<b>Measure, then claim.</b> Quality, latency, cost, citation accuracy, agent success and tool failures are measured; limits are documented with numbers.",
    "<b>Honest status.</b> Implemented-and-tested, partly tested and pending are labelled per requirement."])
S += [p("<b>Verification summary (executed 30 Oct 2026 in the build environment)</b>", H2), table([["Suite", "Result", "Scope"],
      ["Backend (pytest)", f'{facts["pytest_passed"]} passed, 0 failed ({facts["pytest_skipped"]} skipped)', "ingestion incl. a 1,000-page PDF, OCR, migrations, registry/versions/ACL, auth/refresh/roles, RAG, agents, analytics + SQL sandbox, comparison, Self-RAG, reports, memory, metrics/tracing, scheduler, evaluation; real PostgreSQL 16 and Redis 7"],
      ["Frontend (Vitest)", f'{facts["vitest_passed"]} passed', "all screens with mocked HTTP: dashboard, library, exact search, comparison, analyst + charts, reports, history, settings, preview, SSE, token refresh, XSS escaping"],
      ["End-to-end (Playwright)", f'{facts["e2e_steps"]} / {facts["e2e_steps"]} steps', "real server + built app + headless Chromium: sign-up, silent refresh, upload, duplicate and version flow, cited answers, exact search with PDF page preview, parallel answer, incognito, comparison, analyst, PDF report download, theme persistence, admin, role gating"],
      ["Production-shaped smoke", f'{facts["prod_smoke_steps"]} / {facts["prod_smoke_steps"]} checks', "separate API and worker processes, PostgreSQL (data + checkpoints), Redis, CLI tenant bootstrap, production-mode validation, Alembic migrations at start"],
      ["Static checks", "ruff clean; tsc --strict clean; alembic check clean", "lint, type-check, production bundle, migrations match the models"],
      ["Backup / restore", "executed", "pg_dump + data volume -> empty database -> restore -> login and question answered"]], [34, 42, 94]),
      p("Not verifiable here (Appendix A): live OpenAI/Gemini calls, a Qdrant <i>server</i>, the Docker build and Compose run, GitHub Actions, RAGAS, a cross-encoder model, LangSmith, delivery of spans to an OTLP collector.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 2-5 business
S += [p("2. Business Problem and Objectives", H1)] + bullets([
    "Collections reach hundreds or thousands of pages; manual review is slow, and keyword search alone cannot count, compare or reason across files.",
    "Semantic search misses exact names and IDs; spreadsheets need calculation, not similarity; contracts and policies change between versions and teams need to see exactly what changed.",
    "Answers are only useful when verifiable; unverifiable answers are a compliance and trust risk.",
    "Enterprises need identity, roles, tenant isolation, document-level sharing, audit, retention and deletion before adopting AI search on confidential material."])
S += [p("<b>Objectives</b>", H2)] + bullets([
    "<b>BO-1</b> Cited answers over large mixed-format collections.", "<b>BO-2</b> Exact search with complete counts and page/row locations.", "<b>BO-3</b> Reliable calculations on tables (pandas, read-only SQL, charts, trends, anomalies).",
    "<b>BO-4</b> Document intelligence: summaries, comparison and change detection, contradictions, classification, timelines, entities, tables, multilingual (incl. Hindi) retrieval.",
    "<b>BO-5</b> Secure multi-tenant service: JWT + refresh tokens, roles, document ACL, audit, rate limits, retention and deletion.",
    "<b>BO-6</b> Scalable operation: background ingestion, PostgreSQL, Redis, Qdrant, scheduler, metrics and tracing.",
    "<b>BO-7</b> Measurable quality: Recall@K, Precision@K, MRR, citation accuracy, agent success, failed tool calls, latency, tokens, cost.", "<b>BO-8</b> Reports people can share (PDF/DOCX/XLSX) with sources and timestamps."])
S += [p("3. Stakeholders and Roles", H1), table([["Role", "Needs", "Platform permissions"],
      ["User", "Ask, search, summarise, compare, analyse data, generate reports, manage own memory", "ask, read, search, summarize, compare, analytics, web, report, memory"],
      ["Manager", "Curate sources, share documents, run evaluations", "user + ingest (upload, URL, re-index, versions), share, delete own, evaluate"],
      ["Administrator", "Users and roles, audit, organisation policy (retention, web allow-list, redaction), erase data", "manager + manage users, audit, settings, purge, delete any"],
      ["Operator", "Deploy, monitor, back up, upgrade", "environment configuration, CLI, worker, scheduler, /metrics"],
      ["Security / compliance", "Isolation, audit, retention, injection and SSRF defences", "review this BRD, audit log, security tests"]], [28, 72, 70])]
S += [p("4. Scope", H1), p("<b>4.1 In scope</b>", H2)] + bullets([
    "Ingestion of PDF, DOCX, TXT, MD, CSV, XLSX, XLS, JSON, HTML files, URLs and image files (OCR); duplicates, versions, re-index, delete.", "Advanced RAG with Self-RAG option; supervisor with Exact, Document, Data Analyst, Summary, Comparison, Web and Verification agents; parallel execution.",
    "Reports (PDF/DOCX/XLSX); user-controlled memory; roles, refresh tokens, document sharing; retention; metrics, tracing; React UI; evaluation harness; operations documentation."])
S += [p("<b>4.2 Out of scope / not claimed</b>", H2)] + bullets([
    "Execution of code or SQL found in documents or prompts (permanently excluded).", "SSO / OIDC / SAML, MFA, SCIM; compliance certifications.", "Reading values out of chart images; understanding images embedded inside PDFs; relation-type extraction for the knowledge graph (edges are co-mentions).",
    "Neo4j or another graph database; native object storage (a shared volume is used); Celery (the built-in Redis queue is used - decision D1); PaddleOCR (Tesseract is used - D3).",
    "Correct PDF layout of Hindi/Arabic text in generated PDF reports (use DOCX/XLSX)."]) + [PageBreak()]

# ------------------------------------------------------------------ 5 inputs
S += [p("5. Input Formats", H1), p("Every extracted unit carries a location so citations, filters and exact-search results point to the source. Content is validated before parsing (extension allow-list, magic bytes, zip-bomb and macro checks, size and page limits)."),
      table([["Format", "Handling", "Evidence preserved", "Status"],
             ["PDF", "PyMuPDF (unclipped text so off-page glyphs are kept) with pypdf/pdfplumber fallback; bookmarks or font-size headings as sections; ruled tables; OCR for scanned pages; document properties.", "file, version, page, section", status("T", "1,000 pages tested")],
             ["CSV / XLSX / XLS", "Typed pandas tables for analysis, row units for search; header detection; encodings sniffed.", "file, sheet, row, column names", status("T")],
             ["DOCX", "Paragraphs and tables in order, headings as sections, macros rejected, properties.", "paragraph / table + row, section", status("T")],
             ["HTML files, URLs", "Readable text and tables; SSRF-guarded fetch with pinned IP and SNI.", "URL or paragraph, title, section", status("T")],
             ["TXT / MD / JSON", "Paragraphs / headings / flattened JSON paths; BOM, UTF-8, charset detection, cp1252 fallback.", "line, section, JSON path", status("T")],
             ["Images", "Tesseract OCR; optional vision caption.", "'image (OCR)' / 'image caption'", status("P", "captions: scripted model only")]], [26, 74, 42, 28]),
      p("Identity: the sha256 of the file decides. An identical file is refused (existing document returned, unless explicitly allowed); the same name with new content becomes version N+1; older versions are kept for comparison and rollback but are not searched.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 6 functional requirements
FR = [
    ("Ingestion", [
        ("FR-01", "Formats", "PDF, DOCX, TXT, MD, CSV, XLSX, XLS, JSON, HTML, URLs, scanned PDF and PNG/JPG with OCR.", "T"),
        ("FR-02", "Large documents", "1,000+ page PDFs ingest in the background with progress; counts stay exact.", "T"),
        ("FR-03", "Duplicates and versions", "Content hash duplicate refusal; versions; make-current rollback; change detection between versions.", "T"),
        ("FR-04", "Resilience", "Corrupt, truncated, empty, binary, wrong-extension files fail cleanly with a reason; nothing partial is stored.", "T"),
        ("FR-05", "Metadata", "Page, sheet, row, paragraph, section, URL, properties, language, classification, content hash.", "T"),
        ("FR-06", "Delete and re-index", "Delete removes text, chunks, vectors, original; optional all versions; re-index in place.", "T")]),
    ("Document intelligence", [
        ("FR-10", "Exact search", "Full-corpus literal search: counts per document, pages, excerpts, pagination; documented matching rules; CJK/Thai substring rules.", "T"),
        ("FR-11", "Summaries", "Short, detailed, executive, chapter-by-chapter and named-section summaries over the whole document.", "T"),
        ("FR-12", "Comparison and change detection", "Sentence alignment with number changes between documents and between versions.", "T"),
        ("FR-13", "Contradiction detection", "Numeric / negation / antonym candidates across documents; LLM confirmation when configured.", "P"),
        ("FR-14", "Entities, classification, timeline, tables", "Heuristic entities (+ verbatim-validated LLM), closed-taxonomy classification, chronological events with citations, structured table extraction.", "T"),
        ("FR-15", "Cross-document QA", "Evidence from every relevant document is included; no multi-hop reasoning.", "P"),
        ("FR-16", "Multilingual / Hindi", "Unicode tokenisation, Hindi stop-words and routing keywords, Hindi table questions, Hindi summaries; PDF reports do not shape Devanagari.", "P"),
        ("FR-17", "Reports", "Summary, executive, comparison, research, analytics, exact-search and evaluation reports as PDF/DOCX/XLSX with sources and timestamps.", "T")]),
    ("Retrieval", [
        ("FR-20", "Hybrid retrieval", "Semantic, BM25, hybrid (RRF); rewrite; multi-query; HyDE (never evidence); metadata filters; parent-child; compression; reranking; corrective loop.", "T"),
        ("FR-21", "Self-RAG", "Retrieve-or-not, passage relevance, sentence-level support critique, bounded regeneration, removal of unsupported statements.", "T"),
        ("FR-22", "Cross-encoder reranking", "Optional local model; code path only.", "P"),
        ("FR-23", "Vector stores", "Qdrant (production) and ChromaDB (development); Qdrant tested in embedded mode only.", "P"),
        ("FR-24", "Graph RAG", "Entity co-mention graph, neighbour/path queries, retrieval expansion.", "T")]),
    ("Agents", [
        ("FR-30", "Supervisor", "Rules or LLM routing; compound questions fan out in parallel (LangGraph Send) and are merged.", "T"),
        ("FR-31", "Data Analyst", "Pandas operations, profile, duplicates, IQR/z-score anomalies, monthly/quarterly/yearly trends with YoY, top-N, charts; read-only SQL sandbox; NL-to-SQL validated by the sandbox.", "T"),
        ("FR-32", "Comparison Agent", "Documents, versions, topics, contradictions.", "T"),
        ("FR-33", "Web Research", "Per-tenant approved domains, redirect check, separate web evidence (origin=web); a real search provider was not called.", "P"),
        ("FR-34", "Verification", "Number grounding, citation validation against stored text (page/row/excerpt), judge, widened-retrieval retry, strict fallback.", "T"),
        ("FR-35", "Reliability", "Typed state, checkpoints, retry limits, per-node timeouts, transient-error retries, failure isolation per branch.", "T")]),
    ("Memory", [("FR-40", "Conversation memory", "Window + rolling summary, per-user isolation.", "T"), ("FR-41", "User-controlled memory", "Opt-in notes recalled as context (never evidence), incognito, private conversations, reset, delete, sensitive-data refusal, optional redaction.", "T")]),
    ("Security and governance", [
        ("FR-50", "Authentication", "JWT access token (15 min) + rotating refresh token in an httpOnly cookie with reuse detection.", "T"),
        ("FR-51", "Authorisation", "Roles user / manager / admin; tenant and workspace isolation; document-level sharing (organisation / private / users and roles).", "T"),
        ("FR-52", "Protection", "Upload validation, rate limits, audit trail, prompt-injection defences, SSRF protection, SQL authorizer, spreadsheet formula neutralisation.", "T"),
        ("FR-53", "Retention and deletion", "Per-tenant retention enforced by a scheduler (dry run available); erase document, user, memory, tenant.", "T"),
        ("FR-54", "SSO / MFA", "Not implemented.", "N")]),
    ("Platform", [
        ("FR-60", "Database", "PostgreSQL with Alembic migrations and indexes; SQLite for development.", "T"),
        ("FR-61", "Background processing", "Redis-backed queue with status, retries, progress; scheduled tasks.", "T"),
        ("FR-62", "API", "Groups: auth, users/roles, documents, jobs, chat + streaming, exact search, summaries, comparison, analytics, web, reports, memory, evaluation, admin/audit; pagination; OpenAPI (75 operations).", "T"),
        ("FR-63", "User interface", "14 screens, light/dark, streaming, charts, filters, citation navigation with PDF page preview.", "T"),
        ("FR-64", "Observability", "Prometheus metrics, OpenTelemetry spans; LangSmith via environment variables (not verified live).", "P"),
        ("FR-65", "Deployment", "Dockerfile, Compose, CI definitions, backup and restore scripts; image/Compose/CI not executed.", "P")]),
]
S += [p("6. Functional Requirements", H1)]
for grp, rows in FR:
    S += [p(grp, H2), table([["ID", "Requirement", "Description", "Status"]] + [[i, t, d, status(s)] for i, t, d, s in rows], [14, 34, 92, 30])]
S += [PageBreak()]

# ------------------------------------------------------------------ 7 architecture
S += [p("7. Architecture", H1), system_diagram(), Spacer(1, 3 * mm), p("<b>Agent graph.</b> The supervisor routes each question; compound questions (\"count X, and what is the highest Y?\") fan out to parallel branches that each run an agent and a verification pass, then merge into one sectioned answer. "
                                                                         "Generative agents pass through Verification; exact and data answers are deterministic and have their citations validated in the final step."), agent_diagram(), PageBreak(),
      p("<b>Retrieval pipeline.</b> Every step is configurable per request; LLM-dependent steps degrade to deterministic fallbacks.", BODY), rag_diagram(), Spacer(1, 3 * mm),
      p("<b>Data tier.</b> PostgreSQL holds identities, tenants, one row per document <i>version</i> (hash, visibility, metadata), document permissions, jobs, conversations, memory notes, reports, audit events and LangGraph checkpoints. "
        "Content (originals, units, chunks, tables, graphs, reports) lives on the data volume; vectors in Qdrant/Chroma/local. Migrations: 0001 baseline, 0002 registry/versions/ACL/roles/refresh tokens/memory/reports; <font name='Courier'>alembic check</font> proves they match the models."),
      p("<b>Key decisions and trade-offs</b>", H2), table([["Decision", "Rationale", "Trade-off"],
      ["Keep the built-in Redis queue instead of Celery (D1)", "Tested idempotent claim, bounded retries, crash re-delivery; same capability", "No Celery ecosystem tooling (Flower, beat); scheduler is a small dedicated process"],
      ["PyMuPDF with pypdf fallback (D2)", "10-20x faster, headings, page images; unclipped text avoids dropped glyphs", "AGPL-3.0 / commercial licence - operators must decide; pinned below 2.0"],
      ["Tesseract, not PaddleOCR (D3)", "No large model downloads", "Lower accuracy on difficult scans"],
      ["NetworkX graph (D6)", "No extra service; independently testable", "Not for very large graphs; edges are co-mentions"],
      ["SQL via SQLite authorizer sandbox (D7)", "Real SQL semantics, whitelisted operations, time/row limits", "SQLite dialect; spreadsheets are copied in memory per request (cached parse)"],
      ["Citation validation against stored text", "A citation must exist and contain its excerpt", "Spreadsheet cells are re-formatted, so rows use a looser coverage threshold"],
      ["Heuristic contradictions + optional LLM judge", "Works offline; candidates are labelled as such", "False positives/negatives without a model"]], [52, 62, 56]), PageBreak()]

# ------------------------------------------------------------------ 8 security
S += [p("8. Security, Privacy and Data Lifecycle", H1), table([["Layer", "Controls (all exercised by tests unless noted)"],
      ["Identity", "bcrypt; 15-min JWT (memory only in the browser); rotating 14-day refresh token (httpOnly, SameSite=Strict, hashed in DB, family revoked on reuse); roles user/manager/admin; legacy roles migrated."],
      ["Isolation", "tenant + workspace in every storage address; mandatory Qdrant filters; document ACL (organisation / private / restricted to users or roles); hidden = missing."],
      ["Input", "size, magic bytes, zip-bomb, macros; SSRF-safe fetch with pinned IP + SNI; prompt-injection scan, data fences, closed tool registry."],
      ["Execution", "no generated code executed; SQL = one SELECT under an authorizer (function/table whitelist, no PRAGMA/ATTACH/DDL/DML/recursion), length/time/row limits."],
      ["Output", "output guard; citation validation; XLSX formulas neutralised; CSP (self, data:, blob: images); no secrets in logs or audit."],
      ["Data lifecycle", "per-tenant retention (documents, conversations, audit >= 30 days, reports) by scheduler with dry run; erase user / tenant / memory; optional masking of e-mail, phone, card (Luhn), ID numbers and secrets in stored messages (pattern-based, not a guarantee)."],
      ["Operations", "Redis-shared rate limits; append-only audit (hashes, never text); secrets from env or *_FILE (no vault integration); production start-up validator."]], [28, 142]),
      p("<b>Residual risks.</b> Heuristic injection detection can be bypassed; PDF/OCR extraction can be wrong; PyMuPDF licence; a shared volume is a single point of failure and a scaling limit; no SSO/MFA; no penetration test was performed; masking is pattern-based.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 9 evaluation and performance
S += [p("9. Evaluation and Performance (measured)", H1),
      p(f"<b>Synthetic corpus</b> ({M['cases']} questions over PDF, DOCX, XLSX, CSV, MD, TXT, JSON; offline hash embedder, no LLM). The set is small and synthetic: it detects regressions and compares strategies; it is <b>not</b> a real-world accuracy benchmark. Hard paraphrases fail with the offline embedder and are listed in the report."),
      table([["Metric", "Value", "Metric", "Value"],
             ["Recall@5", pct(M["retrieval"]["recall@5"]), "Route accuracy", pct(A["route_accuracy"])],
             ["Precision@5", pct(M["retrieval"]["precision@5"]), "Exact-count accuracy", pct(A["exact_count_accuracy"])],
             ["MRR", f'{M["retrieval"]["mrr"]:.3f}', "Spreadsheet-value accuracy", pct(A["data_accuracy"])],
             ["nDCG@5", f'{M["retrieval"]["ndcg@5"]:.3f}', "Abstained / flagged unanswerable", pct(A["abstained_or_flagged_low_confidence"])],
             ["Citation accuracy", pct(A["citation_accuracy"]), "Faithfulness (lexical proxy)", pct(A["faithfulness_lexical (proxy)"])],
             ["Agent execution success", pct(M["agents"]["execution_success_rate"]), "Failed tool calls", f'{M["agents"]["failed_tool_calls"]} of {M["agents"]["tool_calls"]}'],
             ["Latency p50 / p95", f'{M["latency_ms"]["p50"]:.0f} / {M["latency_ms"]["p95"]:.0f} ms', "Tokens / cost per query", "0 (offline)"]], [38, 28, 62, 42]),
      p(f"<b>Extended corpus</b> ({X['cases']} questions): versions, comparison, contradictions, Hindi (exact, retrieval, table, summary), analytics (trend, outliers), parallel agents, abstention. "
        f"Route accuracy {pct(X['answers']['route_accuracy'])}, keyword accuracy {pct(X['answers']['keyword_accuracy'])}, exact counts {pct(X['answers']['exact_count_accuracy'])}, data values {pct(X['answers']['data_accuracy'])}, required sources cited {pct(X['answers']['required_sources_cited'])}, "
        f"stale (superseded-version) content absent {pct(X['answers']['stale_or_forbidden_content_absent'])}, citation accuracy {pct(X['answers']['citation_accuracy'])}, agent success {pct(AG['execution_success_rate'])}, failed tool calls {AG['failed_tool_calls']}. "
        "Faithfulness and relevancy shown by the harness are lexical/embedding <i>proxies</i>; LLM-judge values and RAGAS need a configured model and the ragas package (not measured here)."),
      p("<b>Performance on this machine</b> (4 vCPU, offline configuration; see docs/PERFORMANCE.md)", H2),
      table([["Workload", "Result"],
             [f"{perf['pages']:,}-page PDF ({pf['mb']} MB, {pf['chunks']:,} chunks)", f"ingest {pf['ingest_s']} s ({pf['pages_per_s']} pages/s) - exact search {perf['exact_search']['ms_p50']} ms with the correct count ({perf['exact_search']['term_count']}) - complete /ask p50 {perf['ask_end_to_end_ms']['p50']} ms"],
             [f"{perf['rows']:,}-row CSV ({cv['mb']} MB)", f"ingest {cv['ingest_s']} s - tables loaded in {cv['load_tables_cold_ms']} ms (then {cv['load_tables_warm_ms']} ms cached) - profile {cv['profile_ms']} ms - monthly trend {cv['trend_ms']} ms - SQL GROUP BY {cv['sql_group_by_ms']} ms"],
             ["Reports", f"summary of the whole {perf['pages']:,}-page document built in {perf['summary_report_s']['build']} s; rendering PDF {perf['summary_report_s']['pdf']} s, DOCX {perf['summary_report_s']['docx']} s, XLSX {perf['summary_report_s']['xlsx']} s"],
             ["Peak memory", f"{perf['peak_rss_mb']} MB for the whole benchmark process"]], [60, 110]), PageBreak()]

# ------------------------------------------------------------------ 10 UI and API
S += [p("10. User Interface and API", H1), table([["Screen", "Purpose"],
      ["Sign-in / registration", "JWT login; silent refresh from the httpOnly cookie after a reload"], ["Dashboard", "document and job counts, library mix by type and class, problems needing attention, quick actions"],
      ["Library + upload + ingestion progress", "drag-and-drop, URLs, per-file progress, duplicate notice with 'upload anyway', search/filter/paginate, versions and what-changed, sharing, class, entities, timeline, re-index, delete"],
      ["Chat", "streaming answers, confidence, citation validity, citations with 'view in context', filters, Self-RAG and incognito toggles, charts, follow-ups, voice"],
      ["Citation preview", "PDF page image with the cited text highlighted and page navigation; passage with neighbours for other formats; web citations marked"],
      ["Exact search", "term, case/whole-word, document filter; totals per document, clickable page numbers, paginated matches"],
      ["Comparison", "two documents, versions of one document, contradiction scan"], ["Data analyst", "ask in words, profile, outliers, trends with YoY, read-only SQL with schema, charts with PNG download"],
      ["Reports", "choose type/format/documents, generate, list, download, delete"], ["History", "search, read, rename, make private, delete conversations"],
      ["Users and roles / Admin", "create, change role, disable, delete; audit log; platform settings; erase tenant data"], ["Settings", "theme (system/light/dark), memory preferences and notes, organisation policy (retention, web allow-list, redaction), retention sweep preview/run"],
      ["Evaluation", "run sample or extended evaluation, strategy comparison, export PDF/DOCX/XLSX"]], [48, 122]),
      p("<b>API groups</b> (75 operations, pagination via limit/offset and X-Total-Count, OpenAPI at /openapi.json and docs/openapi.json): auth, sources (upload, URL, versions, sharing, previews, timeline, classification), jobs, chat (ask, stream, conversations), search/exact, summaries, compare, analytics (tables, profile, anomalies, trend, sql, ask, chart), web/research, reports, memory, eval, admin (users, audit, settings, tenant-settings, maintenance, purge), health, metrics.", BODY), PageBreak()]

# ------------------------------------------------------------------ 11 risks
S += [p("11. Risks, Limitations and Trade-offs", H1), table([["Risk / limitation", "Impact", "Mitigation / status"],
      ["Offline hash embedder is lexical", "paraphrase queries miss", "configure a real embedder; hard cases are listed in the evaluation report"],
      ["Heuristic contradictions", "false positives/negatives", "labelled 'candidate'; LLM judge when configured; manual review"],
      ["PyMuPDF is AGPL/commercial", "licence obligations", "MKA_PDF_ENGINE=pypdf avoids it (slower, no page images)"],
      ["PDF tables only where ruled lines exist", "borderless tables not structured", "text remains searchable"],
      ["Hindi in PDF reports not shaped", "unreadable conjuncts in PDF", "use DOCX/XLSX; text is Unicode"],
      ["Shared data volume", "scaling and single point of failure", "network filesystem now; object storage is future work"],
      ["Node timeouts cannot kill threads", "timed-out work finishes in the background", "client timeouts on providers; result discarded"],
      ["No SSO/MFA; no penetration test", "enterprise onboarding gaps", "planned; hardening documented"],
      ["Docker/Compose/CI not executed here", "first run may need fixes", "files validated statically; process-level smoke test executed"],
      ["Single-node tested only", "multi-replica behaviour", "advisory locks and Redis lock designed for replicas; not load tested"]], [52, 44, 74]), PageBreak()]

# ------------------------------------------------------------------ 12 acceptance
AC = [("AC-01", "A 1,000+ page PDF ingests and an exact name search returns the exact count with pages", "T", "test_large_documents.py"), ("AC-02", "Max sales from an Excel sheet is computed with row citations", "T", "test_tabular.py"),
      ("AC-03", "Semantic question answered with validated citations; missing evidence yields 'could not verify'", "T", "test_agents.py, test_verification_selfrag.py"), ("AC-04", "Two documents / two versions compared; changes with numbers reported", "T", "test_compare.py"),
      ("AC-05", "PDF tables, OCR, DOCX, XLSX, XLS, HTML handled; corrupted files fail cleanly", "T", "test_ingestion_v3.py, test_phase2_ingestion.py"), ("AC-06", "Tenant isolation and unauthorised access are enforced", "T", "test_auth_tenancy.py, test_foundation.py"),
      ("AC-07", "Agent failures and timeouts degrade to honest answers; branches isolated", "T", "test_operations.py"), ("AC-08", "Reports are generated as PDF, DOCX and XLSX with sources and timestamps", "T", "test_reports_memory.py"),
      ("AC-09", "Retention sweeps and erasure work per tenant", "T", "test_operations.py, test_reports_memory.py"), ("AC-10", "Migrations apply to an empty PostgreSQL and match the models; backup/restore works", "T", "test_foundation.py, scripts/backup.sh"),
      ("AC-11", "Full UI flow works in a real browser", "T", "frontend/e2e/smoke.mjs"), ("AC-12", "Quality measured: citation accuracy, agent success, failed tool calls, latency", "T", "test_evaluation.py"),
      ("AC-13", "Live provider behaviour (OpenAI/Gemini), RAGAS, cross-encoder, Qdrant server", "N", "not executed - needs credentials / downloads / services"),
      ("AC-14", "Docker build, Compose stack, GitHub Actions run", "N", "not executed - no container runtime or CI available"), ("AC-15", "Accuracy on a real customer corpus with real models", "N", "pending")]
S += [p("12. Acceptance Criteria", H1), table([["ID", "Criterion", "Status", "Evidence"]] + [[i, c, status(s), e] for i, c, s, e in AC], [14, 78, 30, 48]), Spacer(1, 4 * mm),
      p("<b>Appendix A - What could not be verified, and why</b>", H2)] + bullets([
    "Live OpenAI / Gemini: no credentials or network egress to the providers. All LLM-dependent behaviour was tested with scripted test doubles (orchestration, validation, fallbacks), not model quality.",
    "Qdrant server: starting the binary was not permitted; the embedded client was tested. Hugging Face is unreachable, so no cross-encoder or multilingual embedding model was run.",
    "Docker / Compose / GitHub Actions: no daemon or runner. The workflow, Dockerfile and compose file are written and statically validated only.",
    "RAGAS and LangSmith: packages / network unavailable; the RAGAS adapter was tested with a stub module and LangSmith is configured through environment variables only.",
    "OTLP delivery: spans were verified with an in-memory exporter, not against a collector.",
    "Mobile layouts: CSS breakpoints exist but the UI was only exercised at desktop width."])
S += [p("<b>Appendix B - Documents shipped with the source</b>", H2)] + bullets([
    "README.md (quick start, usage, status) - docs/ARCHITECTURE.md (diagrams) - docs/OPERATIONS.md (deployment, monitoring, backup/recovery, retention, upgrades)",
    "docs/PERFORMANCE.md and docs/perf.json - docs/REQUIREMENTS_TRACE.md - docs/API.md and docs/openapi.json - docs/eval/ (sample and extended evaluation reports in JSON, Markdown, HTML, PDF, DOCX, XLSX) - docs/PLAN_v3.md"])

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="Multi-Agent Knowledge Assistant - BRD v2.1",
                        author="Multi-Agent Knowledge Assistant project", subject="Business Requirements Document")
doc.build(S, onFirstPage=header_footer, onLaterPages=header_footer)
print("wrote", OUT, OUT.stat().st_size, "bytes")
