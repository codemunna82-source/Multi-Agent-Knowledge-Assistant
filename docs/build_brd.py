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
facts = json.loads((HERE / "facts.json").read_text())
M = rep["metrics"]

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


def agent_diagram():
    B, G, O, R = "#e8eefc", "#e5f4ea", "#fdf0dc", "#fbe7e7"
    d = Drawing(520, 262)
    d.add(String(5, 248, "LangGraph StateGraph - typed, checkpointed state (memory | SQLite | PostgreSQL)", fontSize=8, fillColor=colors.HexColor("#1f3a93"), fontName="Helvetica-Bold"))

    def box(x, y, w, h, title, sub, fill):
        d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
        d.add(String(x + w / 2, y + h - 11, title, fontSize=7.4, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
        for i, ln in enumerate(sub.split("\n")):
            d.add(String(x + w / 2, y + h - 20 - i * 8, ln, fontSize=6.6, textAnchor="middle", fillColor=colors.HexColor("#111827")))

    box(5, 100, 86, 40, "Supervisor", "rules | LLM tool-call\n(closed route set)", B)
    ys = {"exact": 205, "semantic": 172, "doc": 139, "data": 106, "sum": 73, "web": 40}
    agents = [("exact", "Exact Search Agent", "regex over full corpus"), ("semantic", "Semantic Retrieval Agent", "advanced RAG + answer"), ("doc", "Document Search Agent", "exact + semantic, listings"),
              ("data", "SQL / Pandas Agent", "controlled table ops"), ("sum", "Summarization Agent", "summary, compare, intel"), ("web", "Web Agent", "SSRF-guarded fetch / search")]
    for k, t, sub in agents:
        box(125, ys[k], 110, 28, t, sub, G)
    box(290, 106, 98, 40, "Verification Agent", "citations, numbers,\nsupport, judge, guard", O)
    box(425, 106, 90, 40, "Final Response", "format, follow-ups,\nlanguage, usage", B)
    box(290, 36, 98, 30, "retry (bounded)", "re-run same agent,\nstrict extractive", R)
    for k in ys:
        _arrow(d, [(91, 120), (125, ys[k] + 14)])
    for k in ("semantic", "doc", "sum", "web"):
        _arrow(d, [(235, ys[k] + 14), (290, 126)])
    _arrow(d, [(388, 126), (425, 126)], ("pass / fail", 389, 131))
    _arrow(d, [(339, 106), (339, 66)], ("retry", 343, 84), dashed=True)
    _arrow(d, [(235, ys["exact"] + 14), (470, ys["exact"] + 14), (470, 146)], ("exact: deterministic, no verification needed", 250, ys["exact"] + 18))
    _arrow(d, [(235, ys["data"] + 14), (262, ys["data"] + 14), (262, 18), (470, 18), (470, 106)], ("data", 400, 21))
    d.add(String(5, 4, "semantic -> Web Agent when abstained and web fallback is enabled;   data -> Semantic Agent when the question is not about the tables", fontSize=6.4, fillColor=colors.HexColor("#374151")))
    return d


def rag_diagram():
    B, G, O = "#e8eefc", "#e5f4ea", "#fdf0dc"
    names = [("Query", "rewrite\n(LLM | merge)", B), ("Variants", "multi-query\nHyDE, x-lingual", B), ("Retrieve", "vector + BM25\nmeta filters", G), ("Fuse", "RRF\n+ graph", G), ("Gate", "relevance\n+ injection", O),
             ("Parents", "parent-child\nde-dupe", G), ("Rerank", "lexical | LLM\ncross-enc.", G), ("Compress", "verbatim\nsentences", G), ("Grade", "correct | weak\n| incorrect", O)]
    d = Drawing(500, 112)
    w, h, gap = 48, 38, 7
    for i, (t, sub, c) in enumerate(names):
        x = 3 + i * (w + gap)
        d.add(Rect(x, 62, w, h, rx=4, ry=4, fillColor=colors.HexColor(c), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
        d.add(String(x + w / 2, 62 + h - 11, t, fontSize=6.8, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
        for j, ln in enumerate(sub.split("\n")):
            d.add(String(x + w / 2, 62 + h - 21 - j * 7.5, ln, fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
        if i:
            _arrow(d, [(x - gap, 81), (x, 81)])
    d.add(Rect(110, 6, 280, 26, rx=4, ry=4, fillColor=colors.HexColor("#fbe7e7"), strokeColor=colors.HexColor("#4a5a8a"), strokeWidth=0.7))
    d.add(String(250, 21, "Corrective loop (bounded by MAX_RETRIES)", fontSize=6.8, fontName="Helvetica-Bold", textAnchor="middle", fillColor=colors.HexColor("#111827")))
    d.add(String(250, 12, "weak/incorrect -> reformulate or broaden, retry; still incorrect -> abstain or web fallback", fontSize=5.7, textAnchor="middle", fillColor=colors.HexColor("#111827")))
    last = 3 + 8 * (w + gap) + w / 2
    _arrow(d, [(last, 62), (last, 19), (390, 19)])
    _arrow(d, [(110, 19), (27, 19), (27, 62)])
    return d


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(18 * mm, 10 * mm, "Multi-Agent Knowledge Assistant - Business Requirements Document v2.0")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


S: list = []
S += [Spacer(1, 40 * mm), p("BUSINESS REQUIREMENTS DOCUMENT", ParagraphStyle("k", parent=BODY, fontSize=10, textColor=colors.HexColor("#6b7280"))), p("Multi-Agent Knowledge Assistant", TITLE),
      p("Enterprise-grade Multi-Agent Knowledge Intelligence Platform", ParagraphStyle("st", parent=BODY, fontSize=13, leading=17, textColor=colors.HexColor("#243b6b"))), Spacer(1, 8 * mm),
      p("<b>Version 2.0</b> (supersedes v1.0 of 29 October 2026) &nbsp;|&nbsp; <b>Date:</b> 30 October 2026"),
      p("<b>Technology:</b> Python 3.12, FastAPI, LangGraph, LangChain-compatible tooling, OpenAI / Gemini (optional), PostgreSQL, Qdrant (production) / ChromaDB (development), Redis, React + TypeScript, Docker"), Spacer(1, 6 * mm),
      table([["Document purpose", "Define the business goals, users, scope, functional and non-functional requirements, architecture, security, evaluation and acceptance criteria for the upgraded platform, and record - honestly - which requirements are implemented, how they were verified, and what remains."],
             ["How to read the status labels", f'{status("T")}: implemented and covered by automated tests that were executed. {status("P")}: implemented, but a dependency (live LLM API, GPU model, container runtime, external server) was not available in the verification environment, so only the stated part was tested. {status("N")}: not implemented.']],
            [38, 132], header=False, zebra=False),
      Spacer(1, 6 * mm), p("<b>Revision history</b>"), table([["Version", "Date", "Change"], ["1.0", "29 Oct 2026", "Initial BRD: PDF/CSV/XLSX/DOCX/TXT/MD/JSON/URL ingestion, hybrid search, exact counts, table analysis, LangGraph routing."],
                                                              ["2.0", "30 Oct 2026", "Enterprise upgrade: multi-tenant auth and RBAC, PostgreSQL/Qdrant/Redis architecture, background workers, advanced RAG, 8-agent supervisor graph with verification, document intelligence, knowledge graph, evaluation framework, React dashboard, security hardening, Docker/CI."]], [18, 24, 128]),
      PageBreak()]

# ------------------------------------------------------------------ 1. Executive summary
S += [p("1. Executive Summary", H1),
      p("The Multi-Agent Knowledge Assistant lets people upload large, mixed-format document collections (or point at public web pages), ask questions in natural language and receive concise answers backed by verifiable evidence - file, page, sheet and row, section, or URL. "
        "Version 1 delivered the core: multi-format ingestion, hybrid retrieval, exact full-corpus search with occurrence counts, controlled spreadsheet analysis and a LangGraph router. Version 2 turns it into a multi-tenant platform: "
        "authenticated users with roles, isolated tenants, durable background ingestion, a production data tier, an advanced retrieval pipeline, a supervisor with eight cooperating agents and a verification step, document intelligence, a measurable evaluation harness and a dashboard."),
      p("<b>Design principles that shape every requirement</b>")] + bullets([
    "<b>Evidence or abstention.</b> Every answer cites its sources; when evidence is insufficient the system says so instead of guessing.",
    "<b>Code computes, models explain.</b> Occurrence counts and spreadsheet figures are produced by deterministic code over the complete data; an LLM, when configured, only phrases grounded answers and may never execute code or SQL.",
    "<b>Documents are data, never instructions.</b> Retrieved text is fenced, scanned and filtered; tools are a closed whitelist.",
    "<b>Isolation by construction.</b> Tenant and workspace are part of every storage address; access control is enforced below the API layer.",
    "<b>Measure, don't assume.</b> Retrieval and answer quality, latency, tokens and cost are measured by a built-in evaluation harness.",
    "<b>Honest status.</b> This document distinguishes implemented-and-tested from untested and pending."])
S += [p("<b>Verification summary (executed on 30 Oct 2026)</b>", H2), table([["Suite", "Result", "Scope"],
      ["Backend (pytest)", f'{facts["pytest_passed"]} passed, 0 failed', "ingestion, OCR, security, auth/RBAC/tenancy, RAG pipeline, agents, data ops, intelligence, evaluation, PostgreSQL, Redis, Qdrant (embedded), ChromaDB"],
      ["Frontend (Vitest)", f'{facts["vitest_passed"]} passed', "API client (incl. SSE), chat, documents, login, role gating, report view, XSS escaping"],
      ["End-to-end (Playwright)", f'{facts["e2e_steps"]} / {facts["e2e_steps"]} steps passed', "real server + built React app + headless Chromium: sign-up, upload, ask (semantic/exact/table), filters, history, evaluation, admin, viewer role"],
      ["Production-shaped smoke", f'{facts["prod_smoke_steps"]} / {facts["prod_smoke_steps"]} checks passed', "separate API and worker processes, PostgreSQL (data + LangGraph checkpoints), Redis queue, CLI tenant bootstrap, production-mode config validation"],
      ["Static checks", "ruff clean; tsc strict clean", "backend lint; frontend type-check and production build"]], [38, 38, 94]),
      p("Not verifiable in the build environment (see Appendix A): live OpenAI/Gemini calls, a Qdrant <i>server</i> (embedded mode was tested), the Docker build, GitHub Actions execution, RAGAS, a cross-encoder model.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 2-5
S += [p("2. Business Problem and Opportunity", H1)] + bullets([
    "Large files hold hundreds or thousands of pages; manual review is slow and error-prone.",
    "Teams need one search across different formats (PDF, spreadsheets, Word, web) without opening each file.",
    "Purely semantic search misses exact names, IDs, dates and cannot count occurrences; spreadsheet questions need calculation, not similarity.",
    "Answers are only useful if users can verify where they came from; unverifiable answers are a compliance and trust risk.",
    "Enterprises require identity, role-based access, tenant isolation, audit trails, rate limiting and data deletion before they can adopt AI search on confidential documents.",
    "Operators need to know quality, latency and cost - and to detect regressions when models or settings change."])
S += [p("3. Business Objectives", H1)] + bullets([
    "<b>BO-1</b> Answer plain-language questions over large mixed-format collections with citations (file, page, sheet/row, section, URL).",
    "<b>BO-2</b> Provide reliable exact search with complete occurrence counts and page/row locations over the entire extracted corpus.",
    "<b>BO-3</b> Provide correct, controlled calculations on CSV/Excel (filter, sort, group, aggregate, duplicates, comparison) without executing generated code.",
    "<b>BO-4</b> Deliver document intelligence: summaries, cross-document comparison, entity and table extraction, question generation, follow-ups, multilingual retrieval, knowledge graph.",
    "<b>BO-5</b> Operate as a secure multi-tenant service: JWT authentication, RBAC, document-level access control, audit logging, rate limiting, deletion.",
    "<b>BO-6</b> Scale ingestion and search through background workers, PostgreSQL, Redis and Qdrant.",
    "<b>BO-7</b> Make quality measurable (Recall@K, Precision@K, MRR, faithfulness, answer relevancy, latency, tokens, cost) and expose it in a dashboard.",
    "<b>BO-8</b> Make uncertainty and missing evidence visible: confidence levels, limitations, and explicit 'could not verify' responses."])
S += [p("4. Stakeholders and Users", H1), table([["Stakeholder / role", "Needs", "Platform role"],
      ["End user / analyst", "Ask questions, check evidence, export findings", "viewer (ask, read) or editor (also upload, re-index, delete own)"],
      ["Knowledge manager", "Curate sources, share or restrict documents, evaluate quality", "editor; document visibility 'organisation' or 'private'"],
      ["Tenant administrator", "Manage users and roles, review audit log, settings, erase data", "admin"],
      ["Platform operator / developer", "Deploy, configure providers and stores, monitor, upgrade", "environment configuration, CLI, worker, CI/CD"],
      ["Security / compliance reviewer", "Review isolation, audit trail, retention and deletion, injection and SSRF defences", "read-only review of this BRD, audit log, security tests"],
      ["Business owner", "Priorities, acceptable cost, success measures", "evaluation dashboard (accuracy, latency, cost/query)"]], [40, 70, 60])]
S += [p("5. Scope", H1), p("<b>5.1 In scope (v2)</b>", H2)] + bullets([
    "Multi-format ingestion with OCR; background ingestion jobs with progress; re-index and delete.", "Advanced RAG, eight-agent LangGraph workflow, verification and bounded retries, conversational memory, streaming.",
    "Structured data analysis; document intelligence; knowledge graph and Graph RAG; image files via OCR and optional vision captions; voice queries.",
    "Authentication, RBAC, multi-tenancy, audit, rate limiting, data deletion; PostgreSQL, Redis, Qdrant/ChromaDB; Docker and CI/CD; React dashboard; evaluation harness and reports."])
S += [p("<b>5.2 Out of scope / explicitly not claimed</b>", H2)] + bullets([
    "Guaranteed accuracy of OCR on poor scans or handwriting; understanding of images embedded inside PDFs (only standalone image files are indexed).", "Autonomous execution of code, SQL or actions found in documents or prompts (permanently excluded).",
    "SSO / OIDC / SAML, MFA, password-reset e-mail, SCIM; legal or certification-level compliance guarantees (SOC 2, ISO 27001, GDPR attestations).", "Relation-type extraction for the knowledge graph (edges are sentence-level co-mentions); real-time collaborative editing.",
    "Horizontal scaling of document storage without a shared volume or object store (see Risks)."]) + [PageBreak()]

# ------------------------------------------------------------------ 6 input formats
S += [p("6. Input Formats", H1), p("Every extracted unit carries a location so that citations, filters and exact-search results can point to the original source."),
      table([["Format", "Handling", "Evidence preserved", "Status"],
             ["PDF", "Per-page text (pypdf); OCR fallback for scanned pages (Tesseract, MKA_OCR_ENABLED); bookmarks become section metadata; ruled tables extracted structurally (pdfplumber); page cap.", "file name, document ID, page, section (when bookmarks exist)", status("T", "OCR tested with a generated scanned PDF")],
             ["CSV / Excel (.xlsx)", "Row units for search; full table kept for analysis; header = first non-empty row; encodings and delimiters sniffed.", "file name, sheet, spreadsheet row number, column names", status("T")],
             ["DOCX", "Paragraphs and tables in document order; headings tracked as sections; macros rejected.", "file name, paragraph / table + row, section", status("T")],
             ["TXT / Markdown", "Paragraph blocks; Markdown headings tracked.", "file name, line, section", status("T")],
             ["JSON", "Leaf values flattened to JSON paths.", "file name, JSON path", status("T")],
             ["Public web URL", "SSRF-guarded fetch (resolve once, connect by IP, verified SNI), readable-text extraction, HTML tables, canonical URL kept.", "URL, title, section", status("T", "TLS pinning tested with a local TLS server")],
             ["Images (PNG/JPEG/TIFF/WebP)", "OCR text; optional caption from a vision-capable LLM (MKA_VISION_CAPTIONS).", "file name, 'image (OCR)' / 'image caption'", status("P", "OCR tested; captions tested with a scripted model only")]],
            [28, 74, 40, 28]),
      p("<b>Validation before parsing</b>: extension allow-list, magic-byte / container checks (PDF header, OOXML structure, image signatures, no binary data in text formats), zip-bomb limits, macro rejection, size limit, PDF page limit, filename sanitisation.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 7 functional requirements
FR = [
    ("FR-01", "File upload", "Accept supported files, validate type/size, return per-file ingestion status; multi-file; synchronous or queued.", "T", "Must"),
    ("FR-02", "Web ingestion", "Public HTTP(S) URL with canonical URL retained; private/local/redirect-to-private targets blocked; DNS-rebinding-safe.", "T", "Must"),
    ("FR-03", "Content extraction & metadata", "Pages, sheets/rows, sections, URLs, document IDs preserved for every unit; tables extracted as structured data.", "T", "Must"),
    ("FR-04", "Chunking & indexing", "Chunks never cross page/sheet/table/section boundaries; embeddings stored in the configured vector store with tenant/workspace scope.", "T", "Must"),
    ("FR-05", "Exact search", "Literal name/ID/phrase search over the complete extracted corpus; documented matching rules; total count, file, page numbers, excerpts; not top-K limited.", "T", "Must"),
    ("FR-06", "Semantic search", "Vector retrieval of conceptually relevant passages with source excerpts.", "T", "Must"),
    ("FR-07", "Structured data analysis", "Controlled pandas operations: filter, sort/top-N, group, sum, mean, median, min/max, distinct, duplicates, two-table comparison; never executes generated code.", "T", "Must"),
    ("FR-08", "Multi-agent routing", "Supervisor routes to Exact, Semantic, Document Search, Web, SQL/Pandas, Summarization agents; rules by default, optional validated LLM tool-calling.", "T", "Must"),
    ("FR-09", "Evidence-based answers", "Answers carry citations and excerpts; insufficient evidence yields an explicit 'could not verify' (verified=false).", "T", "Must"),
    ("FR-10", "Cross-source questions", "Per-source retrieval and side-by-side comparison; LLM match/conflict analysis when configured.", "P", "Should"),
    ("FR-11", "Conversation context", "Per-conversation memory (window + rolling summary), follow-up resolution, isolation between users.", "T", "Should"),
    ("FR-12", "Error handling", "Clear errors for unsupported/corrupt/empty files, invalid URLs, provider errors, indexing failures; no partial ingestion.", "T", "Must"),
    ("FR-13", "Re-ingestion and removal", "Re-index and delete a source; text, chunks, vectors and original removed consistently.", "T", "Should"),
    ("FR-14", "API access", "Documented FastAPI endpoints (OpenAPI), typed schemas, request IDs.", "T", "Must"),
    ("FR-15", "Advanced RAG", "Semantic, BM25 and hybrid search; query rewriting; multi-query; HyDE; metadata filtering; parent-child retrieval; contextual compression; reranking; corrective RAG - each configurable globally and per request.", "P", "Must"),
    ("FR-16", "Supervisor and agents", "LangGraph StateGraph with typed state, conditional edges, tool registry (validated arguments), checkpointing, bounded retries, session memory; eight agents including Verification and Final Response.", "T", "Must"),
    ("FR-17", "Verification", "Citation-marker, number-grounding, lexical-support and optional LLM-judge checks; bounded retries; verbatim fallback; output guard against prompt leaks and exfiltration URLs.", "T", "Must"),
    ("FR-18", "OCR", "Scanned PDF pages and image files read with Tesseract; OCR'd pages are flagged in warnings.", "T", "Must"),
    ("FR-19", "Document intelligence", "Summaries (map-reduce), entity extraction (heuristic + verbatim-validated LLM), table extraction, question generation, follow-up suggestions, language detection, multilingual answering and cross-lingual retrieval.", "P", "Should"),
    ("FR-20", "Knowledge graph / Graph RAG", "Sentence-level entity co-occurrence graph per accessible documents; neighbour/path queries; optional retrieval expansion.", "T", "Could"),
    ("FR-21", "Multimodal and voice", "Image OCR/captions; voice via browser speech recognition or server-side transcription.", "P", "Could"),
    ("FR-22", "Streaming", "Server-Sent Events: real graph progress steps, answer pieces, final structured response.", "P", "Should"),
    ("FR-23", "Background ingestion", "Durable jobs with progress, idempotent claim, bounded retries for transient failures, in-process or Redis workers.", "T", "Must"),
    ("FR-24", "Authentication & RBAC", "JWT (bcrypt passwords, revocation), roles viewer/editor/admin, role changes effective immediately, last-admin protection.", "T", "Must"),
    ("FR-25", "Multi-tenancy & document ACL", "Tenant+workspace isolation at storage, vector and graph level; 'private' documents visible to owner and admins only.", "T", "Must"),
    ("FR-26", "Audit logging", "Append-only audit events with request ID, user, IP, outcome; question text never stored (hash + length only).", "T", "Must"),
    ("FR-27", "Rate limiting", "Per-user/IP limits for ask, ingest, auth; shared across replicas via Redis; 429 with Retry-After.", "T", "Must"),
    ("FR-28", "Data deletion", "Delete source, conversation, workspace; admin purge of all tenant data with typed confirmation.", "T", "Must"),
    ("FR-29", "Evaluation", "Recall@K, Precision@K, nDCG, MRR, routing/count/data/abstention accuracy, faithfulness and relevancy (proxy and LLM-judge), RAGAS adapter, latency, tokens, cost; dashboard and reports; strategy comparison.", "P", "Must"),
    ("FR-30", "Web dashboard", "React + TypeScript: login, multi-upload with progress, document management, chat with citations and filters, history, evaluation dashboard, admin.", "T", "Must"),
]
NOTES = {
    "FR-10": "LLM conflict analysis tested with a scripted model; side-by-side evidence tested for real.", "FR-15": "All techniques tested; LLM-dependent ones (HyDE, LLM rerank/compress/grade) with a scripted model; cross-encoder not installed.",
    "FR-19": "LLM paths tested with a scripted model; heuristic entity extraction covers Latin-script names only.", "FR-21": "Whisper transcription mock-tested; captions scripted; images inside PDFs not indexed.",
    "FR-22": "Answer text is streamed after generation; provider token streaming not implemented."}
S += [p("7. Functional Requirements", H1), p("Priority uses MoSCoW. FR-01 to FR-14 carry over from v1 (strengthened); FR-15 to FR-30 are new in v2."),
      table([["ID", "Requirement", "Description", "Pri.", "Status"]] + [[i, t, d, pr, status(s, NOTES.get(i, ""))] for i, t, d, s, pr in FR], [12, 28, 83, 9, 38]), PageBreak()]

# ------------------------------------------------------------------ 8 NFR
S += [p("8. Non-Functional Requirements", H1), table([["ID", "Area", "Requirement", "How it is met / verified"],
      ["NFR-1", "Accuracy", "Answers grounded in retrieved or calculated evidence; exact counts scan the full relevant corpus; abstain when unverifiable.", "Exact search is regex over all units (test: 40-page PDF count); verification agent; evaluation: exact-count accuracy 100% on the sample set."],
      ["NFR-2", "Performance", "Targets set per deployment from measurement, not assumed.", f'Sample corpus (offline, no LLM): p50 {M["latency_ms"]["p50"]:.0f} ms, p95 {M["latency_ms"]["p95"]:.0f} ms end-to-end. LLM-backed latency depends on the provider and was not measured.'],
      ["NFR-3", "Scalability", "Batch processing; never place a whole large file in one prompt; asynchronous ingestion.", "Chunking, map-reduce summaries, queue + workers (tested with Redis and a separate worker). BM25 index is rebuilt in memory per workspace - suited to tens of thousands of chunks; larger corpora need a search engine (Risk R-4)."],
      ["NFR-4", "Security", "See section 13.", "Automated tests per control."],
      ["NFR-5", "Privacy", "No cross-tenant or cross-user exposure; retention and deletion controls; no document text in logs or audit.", "Isolation tests across tenants, workspaces, private documents, conversations, graph; purge test."],
      ["NFR-6", "Reliability", "Failures visible and retryable where safe; partial ingestion never shown as complete.", "Atomic stage-and-rename commit; job retry policy; idempotent job claim; tests for outage/retry."],
      ["NFR-7", "Maintainability", "Modular adapters, typed schemas, tests, configuration-driven providers and stores.", "Pydantic everywhere; ruff clean; strict TypeScript; provider/vector/queue/checkpoint backends behind interfaces."],
      ["NFR-8", "Observability", "Structured logs, request IDs, usage and cost tracking, audit trail.", "JSON logs with request ID; per-request token/cost metering; /health usage counters; audit API."],
      ["NFR-9", "Portability", "Run locally without external services; run in containers with PostgreSQL, Redis, Qdrant.", "Defaults need no keys (SQLite, local vectors, hash embedder). Compose file validated syntactically; image build not executed (no container runtime)."],
      ["NFR-10", "Usability", "Accessible, responsive dashboard; clear errors; no HTML injection from documents.", "ARIA labels, responsive CSS; XSS test; keyboard-operable upload."]], [14, 25, 58, 73]), PageBreak()]

# ------------------------------------------------------------------ 9 agent architecture
S += [p("9. Multi-Agent Architecture", H1),
      p("A LangGraph <b>StateGraph</b> coordinates specialised agents. State is typed and JSON-serialisable so it can be <b>checkpointed</b> (memory, SQLite or PostgreSQL) per conversation thread; heavy objects (principal, stores) live in a per-request context, never in the checkpoint."),
      agent_diagram(), Spacer(1, 3),
      table([["Agent", "Responsibility", "Tools it may use", "Verified"],
             ["Supervisor", "Chooses the route from the question and available sources (rules; optional LLM tool-calling restricted to a closed set, with rules as fallback).", "routing rules / closed route set", "route table test; LLM mode: valid, invalid and disallowed choices"],
             ["Exact Search Agent", "Literal name/ID/phrase search over the whole extracted corpus; count, files, pages, excerpts; asks for the term when missing.", "exact_search", "count/page tests; evaluation 100%"],
             ["Semantic Retrieval Agent", "Runs the advanced RAG pipeline, builds a grounded answer (LLM or verbatim extraction), abstains when evidence is missing.", "hybrid_search", "recall/MRR on sample set; abstention"],
             ["Document Search Agent", "Which documents mention X, clause lookups, document listing; combines exact and semantic evidence.", "exact_search, hybrid_search, list_sources", "clause 8 vs 80 vs 8.1 tests"],
             ["SQL / Pandas Agent", "Turns a question into a whitelisted plan (heuristic or validated LLM JSON) and executes it with pandas; asks for clarification when ambiguous; hands over when the question is not about the tables.", "table_query", "aggregate tests vs manual calculation"],
             ["Summarization Agent", "Map-reduce summaries; cross-document comparison; entity, table and question extraction; knowledge-graph questions.", "summarize, hybrid_search", "summary/compare/entity/graph tests"],
             ["Web Agent", "Reads URLs given in the question or search results (SSRF-guarded); transient evidence, never auto-indexed; optional fallback when documents cannot answer.", "fetch_url, web search provider", "mock-transport tests; SSRF tests"],
             ["Verification Agent", "Checks citations, numbers, lexical support, optional LLM judge, output guard; decides pass / retry (bounded) / fail (verbatim fallback).", "-", "retry, exhaustion, judge, guard tests"],
             ["Final Response Agent", "Assembles the response: citations, limitations, confidence, follow-up questions, language, trace, usage.", "-", "API/e2e tests"]], [32, 76, 32, 30]),
      p("<b>Other behaviour</b>: bounded retries (MAX_RETRIES) in both corrective RAG and verification; session memory = last N turns plus a rolling summary of older turns; every node degrades to an honest message on internal error instead of a 500; tool arguments are validated (Pydantic) and there is no tool that executes code, SQL or shell commands.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 10 RAG
S += [p("10. Advanced RAG Architecture", H1), p("The pipeline is configurable globally (environment) and per request (<font face='Courier'>retrieval</font> object). Every step is recorded in a trace for debugging and evaluation."), rag_diagram(), Spacer(1, 3),
      table([["Technique", "How it works here", "Config key", "Default", "Without an LLM"],
             ["Semantic search", "Cosine over embeddings (local, Chroma or Qdrant); tenant/workspace filter mandatory.", "RETRIEVAL_MODE", "hybrid", "hash embedder is lexical, not semantic"],
             ["BM25 / keyword", "Okapi BM25 with inverted index; fuzzy prefix expansion on corrective passes.", "RETRIEVAL_MODE", "hybrid", "works"],
             ["Hybrid", "Reciprocal-rank fusion of every (query variant x channel) ranking.", "RETRIEVAL_MODE", "hybrid", "works"],
             ["Query rewriting", "LLM standalone-query rewrite from conversation; otherwise follow-up merge with previous question.", "QUERY_REWRITE", "on", "context merge"],
             ["Multi-query", "LLM paraphrases (incl. other languages); otherwise keyword-only variant.", "MULTI_QUERY", "off", "keyword variant"],
             ["HyDE", "Embeds an LLM-written hypothetical answer for vector search (never shown).", "HYDE", "off", "skipped (reported in trace)"],
             ["Metadata filtering", "kinds, name, page range, sheet, section, ingestion date; applied before ranking.", "retrieval.filters", "none", "works"],
             ["Parent-child", "Small chunks are matched; their page/section parent is returned; siblings de-duplicated.", "PARENT_CHILD", "on", "works"],
             ["Contextual compression", "Keep only query-relevant sentences, verbatim (LLM choices must literally occur in the source).", "COMPRESSION", "on", "extractive"],
             ["Reranking", "Lexical (coverage, BM25, phrase), LLM scoring, or optional cross-encoder.", "RERANKER", "lexical", "lexical"],
             ["Corrective RAG", "Grade evidence; on weak/no evidence reformulate or broaden and retry (bounded), else abstain or web fallback.", "CORRECTIVE, MAX_RETRIES", "on, 2", "heuristic grading"],
             ["Graph RAG", "Adds chunks linked to query entities and their strongest neighbours.", "GRAPH_RAG", "off", "works"],
             ["Cross-lingual", "LLM translates the question into the languages of the indexed documents.", "CROSS_LINGUAL", "on", "skipped"]], [26, 60, 36, 14, 34]),
      p("<b>Safety in the pipeline</b>: passages sent to an LLM are fenced as untrusted data with neutralised control markup; suspected injections are flagged (or excluded with INJECTION_POLICY=exclude); every LLM output is validated and failures fall back to deterministic behaviour.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 11 platform architecture
S += [p("11. Platform and Data Architecture", H1), table([["Component", "Role", "Notes"],
      ["FastAPI", "REST + SSE API, OpenAPI docs, static React dashboard", "request IDs, JSON logs, security headers, CORS allow-list"],
      ["PostgreSQL", "Tenants, users, revoked tokens, audit events, jobs, conversations/messages, evaluation runs; LangGraph checkpoints", "SQLite for development; schema created at start (no migration tool yet - Risk R-6)"],
      ["Qdrant (production) / ChromaDB (dev) / local", "Vector index. Qdrant: one collection per embedding dimension; tenant, workspace and source in the payload; mandatory filters on every search and delete", "server mode not tested here; embedded mode and the isolation contract were"],
      ["Redis", "Shared rate limiting; ingestion job queue (reliable move to a processing list, crash re-delivery)", "falls back to in-process when not configured"],
      ["Worker", "<font face='Courier'>python -m app.worker</font>: executes ingestion jobs; shares the data volume with the API", "atomic claim makes duplicate delivery harmless"],
      ["Document store", "Per source: original file, units, chunks, vectors (local mode), tables, graph, metadata; staged then atomically renamed", "filesystem volume; object storage is future work (Risk R-3)"],
      ["Tenancy", "Address = tenant / workspace / source; no API crosses tenants; private documents filtered below the API", "X-Session-ID selects the workspace within the tenant"],
      ["React dashboard", "Single-page app served by the API", "JWT kept in sessionStorage (Risk R-7)"]], [32, 88, 50]), PageBreak()]

# ------------------------------------------------------------------ 12 API
S += [p("12. API Requirements", H1), p("Full reference: <font face='Courier'>docs/API.md</font> (generated from the application), interactive Swagger UI at <font face='Courier'>/docs</font>. Conventions: bearer JWT, <font face='Courier'>X-Session-ID</font> workspace header, <font face='Courier'>X-Request-ID</font> correlation, JSON errors, <font face='Courier'>429</font> with <font face='Courier'>Retry-After</font>."),
      table([["Area", "Endpoints", "Minimum role"],
             ["System", "GET /health", "public"], ["Auth", "POST /auth/signup (dev only), /auth/login, /auth/logout; GET /auth/me", "public / any"],
             ["Sources", "POST /sources/upload[?async=true], /sources/url, /sources/{id}/reindex; GET /sources, /sources/{id}, /sources/{id}/tables|entities|questions; DELETE /sources/{id}", "viewer read; editor write; owner/admin modify"],
             ["Jobs", "GET /jobs, /jobs/{id}", "editor"],
             ["Chat", "POST /ask, /ask/stream (SSE); GET/POST /conversations, GET /conversations/{id}/messages|trace; DELETE /conversations/{id}; POST /transcribe", "viewer"],
             ["Intelligence", "GET /graph (top entities, neighbours, path)", "viewer"],
             ["Evaluation", "POST /eval/run; GET /eval/runs, /eval/runs/{id}, /report.html, /report.md", "editor"],
             ["Admin", "GET/POST /admin/users, PATCH/DELETE /admin/users/{id}; GET /admin/audit, /admin/settings; DELETE /admin/data, /session", "admin"]], [24, 112, 34]),
      p("<b>/ask response</b>: answer, route, confidence (high|medium|low|none), verified, citations[{source, location, excerpt, score}], limitations, needs_input, follow-up questions, language, usage (tokens, cost), latency, details (plan, verification, retrieval trace, counts, table results).", SMALL), Spacer(1, 4)]

# ------------------------------------------------------------------ 13 security
SEC = [
    ("Prompt injection in documents or questions", "Ingestion-time scan; fenced untrusted data with neutralised markup; closed tool registry (no code/SQL/shell); output guard (prompt-leak, exfiltration URLs); optional exclude policy; LLM numbers/citations verified", "tests: pattern detection and false-positive set, fence forgery, guard, injected document end-to-end", "T"),
    ("SSRF and DNS rebinding", "Scheme/credential checks; resolve once; reject non-public addresses (incl. IPv4-mapped IPv6); connect by vetted IP with verified SNI; every redirect re-validated; size/time/type limits", "tests: private ranges, metadata endpoint, redirect-to-private, rebinding with a local TLS server and wrong-certificate rejection", "T"),
    ("Malicious or malformed files", "Extension allow-list; magic bytes; OOXML structure; zip-bomb and macro rejection; binary-in-text detection; size and page limits; safe filenames", "tests for each rejection", "T"),
    ("Authentication", "bcrypt, constant-time-ish login, JWT with required claims, revocation list, disabled-account and role changes effective immediately, `alg=none`/forged/expired tokens rejected", "auth test-suite", "T"),
    ("Authorisation and tenant isolation", "RBAC per route; tenant+workspace addressing; mandatory Qdrant filters; ACL-filtered graph and retrieval; hidden documents look missing", "cross-tenant, private-document, conversation, job, graph and evaluation isolation tests", "T"),
    ("Abuse / DoS", "Per-identity rate limits (memory or Redis); upload and PDF page limits; bounded retries; request timeouts", "rate-limit tests incl. two replicas via Redis", "T"),
    ("Secrets", "Keys only from environment; SecretStr; masked admin settings; production start-up validator rejects insecure config", "config validation and masking tests; production smoke", "T"),
    ("Auditability", "Append-only events with request ID, user, IP, outcome; no document or question text", "audit content/privacy tests", "T"),
    ("Data deletion / retention", "Delete source/conversation/workspace; tenant purge; no automated retention schedule yet", "deletion and purge tests", "P"),
    ("XSS in the dashboard", "All document/answer text rendered as text; CSP and security headers", "Vitest injection test, Playwright run with no console errors", "T")]
S += [p("13. Security Requirements", H1), table([["Threat", "Controls", "Verification", "Status"]] + [[a, b, c, status(s)] for a, b, c, s in SEC], [34, 78, 38, 20]),
      p("<b>Residual risks</b>: no SSO/MFA; JWT in browser sessionStorage; rate limiting trusts the direct client address unless a proxy sets it; heuristic injection scanning cannot catch every phrasing (defence in depth, not a guarantee); 'X-Forwarded-For' is not trusted by default.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 14 evaluation
r, a, lat = M["retrieval"], M["answers"], M["latency_ms"]
S += [p("14. Evaluation Metrics", H1), p("The harness (<font face='Courier'>python -m app.eval</font>, <font face='Courier'>POST /eval/run</font>, dashboard tab) runs a labelled dataset through the real pipeline and agents and reports:"),
      table([["Metric", "Definition"], ["Recall@K", "share of gold passages found in the top K retrieved (K = 1, 3, 5)"], ["Precision@K", "relevant results in the top K divided by K"], ["MRR", "mean of 1/rank of the first relevant result"], ["nDCG@K", "binary-relevance discounted gain"],
             ["Faithfulness", "<i>proxy</i>: share of answer sentences whose content words and numbers occur in the cited evidence; LLM-judge variant when an LLM is configured; RAGAS adapter available"],
             ["Answer relevancy", "<i>proxy</i>: cosine(question, answer) under the configured embedder; LLM-judge variant when configured"], ["Routing / count / data accuracy", "expected route, exact occurrence count, numeric result match"], ["Abstention accuracy", "unanswerable questions must return verified=false (or low confidence, reported separately)"],
             ["Latency", "end-to-end per question: mean, p50, p95; retrieval-only p50/p95"], ["Tokens and cost", "provider-reported when available else ~4 chars/token; USD from MKA_PRICE_TABLE"]], [40, 130]),
      p(f'<b>Measured on the built-in synthetic corpus</b> ({M["cases"]} questions over 8 mixed-format documents; offline: hash embedder, no LLM; run {rep["created"]}):', H2),
      table([["Metric", "Value", "Metric", "Value"],
             ["Recall@1 / @3 / @5", f'{pct(r["recall@1"])} / {pct(r["recall@3"])} / {pct(r["recall@5"])}', "Routing accuracy", pct(a["route_accuracy"])],
             ["Precision@1 / @3 / @5", f'{pct(r["precision@1"])} / {pct(r["precision@3"])} / {pct(r["precision@5"])}', "Exact-count accuracy", pct(a["exact_count_accuracy"])],
             ["MRR", f'{r["mrr"]:.3f}', "Data (table) accuracy", pct(a["data_accuracy"])],
             ["Faithfulness (proxy)", pct(a["faithfulness_lexical (proxy)"]), "Abstention accuracy (strict)", pct(a["abstention_accuracy"])],
             ["Answer relevancy (proxy)", pct(a["answer_relevancy_embedding (proxy)"]), "Keyword correctness (semantic)", pct(a["keyword_accuracy"])],
             ["Latency p50 / p95", f'{lat["p50"]:.0f} / {lat["p95"]:.0f} ms', "Tokens / cost per query", f'{M["tokens"]["per_query"]:.0f} / ${M["cost_usd"]["per_query"]:.5f}']], [42, 43, 45, 40]), Spacer(1, 3)]
cmp_rows = [["Strategy", "Recall@5", "MRR", "nDCG@5", "p50 ms"]] + [[c["strategy"], pct(c["recall@5"]), f'{c["mrr"]:.3f}', f'{c["ndcg@5"]:.3f}', f'{c["p50_ms"]:.1f}'] for c in rep["comparison"]]
S += [p("<b>Strategy comparison</b> (same corpus):", BODY), table(cmp_rows, [78, 24, 24, 24, 20]),
      p("<b>How to read these numbers.</b> The corpus is small and synthetic; it detects regressions and compares settings, it is <u>not</u> a benchmark of real-world accuracy. With the offline hash embedder the semantic and keyword channels are both lexical, so the hybrid advantage appears only with a real embedding model. "
        "Hard paraphrases with no word overlap (e.g. 'vacation time' vs 'annual leave') fail by design and are listed in the report's failures. The proxy metrics are not RAGAS; LLM-judge and RAGAS values require a configured model and were not measured here.", SMALL), PageBreak()]

# ------------------------------------------------------------------ 15 acceptance
AC = [
    ("AC-1", "A text PDF is ingested and searched; returned matches carry the correct page numbers.", "T"),
    ("AC-2", "A scanned PDF is rejected with a clear message without OCR and indexed with OCR; OCR'd pages are flagged.", "T"),
    ("AC-3", "CSV/XLSX aggregates (sum, mean, median, max, min, group, filter, sort, duplicates, comparison) equal a trusted manual calculation; ambiguous questions trigger a clarification instead of a guess.", "T"),
    ("AC-4", "An exact-name query returns the total count, file names, page numbers and excerpts over the complete corpus (40-page test), with documented rules (case, whole word, clause 8 vs 8.1 vs 80).", "T"),
    ("AC-5", "A public page is ingested and cited by URL; private, local, metadata-service and redirect-to-private URLs are rejected; DNS rebinding cannot redirect the connection.", "T"),
    ("AC-6", "A semantic question returns relevant passages with citations; an unrelated question returns an explicit 'could not verify' (verified=false).", "T"),
    ("AC-7", "A generated answer containing an invented number or no citations is retried (bounded) and finally replaced by verbatim evidence.", "T"),
    ("AC-8", "Users of tenant A cannot list, read, search, cite, graph or delete anything of tenant B; private documents are invisible to other users in the same tenant; role limits are enforced.", "T"),
    ("AC-9", "Ingestion runs in the background with visible progress; transient failures are retried at most N times; invalid input is not retried; a separate Redis worker processes jobs.", "T"),
    ("AC-10", "Rate limits return 429 with Retry-After and are shared by multiple API replicas through Redis.", "T"),
    ("AC-11", "The audit log records ingest, ask, login, permission denials and deletions without storing question or document text.", "T"),
    ("AC-12", "Deleting a source or purging a tenant removes files, chunks and vectors; deleted material is no longer retrievable.", "T"),
    ("AC-13", "The evaluation harness reports Recall@K, Precision@K, MRR, faithfulness, relevancy, latency, tokens and cost, and fails CI when retrieval quality drops below the regression thresholds.", "T"),
    ("AC-14", "The dashboard supports multi-upload with progress, document management, chat with citations and filters, history, evaluation, admin; document text cannot inject HTML.", "T"),
    ("AC-15", "With a real LLM and embedding provider, answer quality, faithfulness (judge/RAGAS) and cost meet targets agreed with the business owner on a representative corpus.", "N"),
    ("AC-16", "The container images build and the compose stack starts with PostgreSQL, Redis and a Qdrant server; Qdrant server mode passes the vector-backend contract tests.", "N")]
S += [p("15. Acceptance Criteria", H1), table([["ID", "Criterion", "Status"]] + [[i, c, status(s)] for i, c, s in AC], [14, 128, 28]), PageBreak()]

# ------------------------------------------------------------------ 16 roadmap
S += [p("16. Development Roadmap", H1), table([["Phase", "Deliverables", "Exit condition", "State"],
      ["1 Platform foundation", "PostgreSQL model, JWT auth, RBAC, tenant-scoped storage, document ACL, rate limiting, audit, purge, production config validation", "isolation and RBAC tests pass (incl. PostgreSQL, Redis)", status("T")],
      ["2 Ingestion", "File validation, OCR, PDF sections/tables, images, DNS-rebinding-safe fetch, background jobs, Qdrant backend", "format, security and job tests pass", status("T")],
      ["3 Advanced RAG", "Hybrid, rewrite, multi-query, HyDE, filters, parent-child, compression, rerank, corrective", "technique tests and trace assertions pass", status("T")],
      ["4 Agents", "Supervisor + 8 agents, tool registry, checkpointing, verification, memory, streaming", "routing, verification, memory, checkpoint tests pass", status("T")],
      ["5 Intelligence", "Data ops, entities, tables, questions, multilingual, knowledge graph, voice", "operation and isolation tests pass", status("T")],
      ["6 Evaluation", "Metrics, harness, reports, dashboard API, regression thresholds", "sample evaluation within thresholds", status("T")],
      ["7 Frontend", "React dashboard, unit and end-to-end tests", "e2e smoke passes against the real server", status("T")],
      ["8 Delivery", "Docker, compose, CI workflow, documentation, this BRD", "documents produced; container build pending", status("P", "image build and CI run not executed here")],
      ["Next A", "Validate with real providers: embeddings, LLM, RAGAS, cross-encoder; tune thresholds; cost budget", "AC-15", status("N")],
      ["Next B", "Run on the container runtime and Qdrant server; Alembic migrations; object storage; OIDC/SSO and MFA; refresh tokens; retention scheduler; provider token streaming", "AC-16 and hardening backlog", status("N")]], [28, 78, 40, 24])]

# ------------------------------------------------------------------ 17 risks
S += [p("17. Risks and Dependencies", H1), table([["ID", "Risk", "Impact", "Mitigation / status"],
      ["R-1", "Offline default embedder is lexical; paraphrase recall is limited", "missed passages on conceptual questions", "configure OpenAI/Gemini embeddings; evaluation reports failures; hard cases tracked"],
      ["R-2", "LLM-dependent features were tested with scripted models only", "unknown real-world quality/cost", "AC-15; evaluation harness with LLM judge and RAGAS; verification agent bounds damage"],
      ["R-3", "Documents live on a filesystem volume shared by API and worker", "horizontal scaling and DR need shared storage", "volume today; object storage on the roadmap"],
      ["R-4", "BM25 index is built in memory per workspace", "memory/latency on very large corpora", "OpenSearch / PostgreSQL full-text search planned"],
      ["R-5", "OCR quality depends on scans; images inside PDFs not indexed", "missed content", "OCR flagged in warnings; roadmap item"],
      ["R-6", "No migration tool (schema created at start)", "upgrades need manual care", "adopt Alembic before first production upgrade"],
      ["R-7", "JWT in sessionStorage; no SSO/MFA", "token theft if XSS ever occurs", "strict CSP, text-only rendering, short token life; OIDC + httpOnly cookies planned"],
      ["R-8", "Heuristic prompt-injection detection is evadable", "residual injection risk", "defence in depth: data fences, closed tools, output guard, verification, exclude policy"],
      ["R-9", "Embedding/LLM usage cost", "operating cost", "per-request token/cost metering, rate limits, price table, evaluation of cost per query"],
      ["R-10", "Web pages change or block extraction", "stale or missing web evidence", "URL and ingestion time retained; re-index re-fetches"],
      ["R-11", "Qdrant server, Docker build and CI were not executed in the build environment", "integration surprises", "AC-16; compose file validated; embedded Qdrant passes the same contract tests"]], [12, 58, 40, 60]),
      p("<b>Dependencies</b>: Python 3.12, PostgreSQL 16, Redis 7, Qdrant (production), Tesseract OCR binary, LLM/embedding provider credentials supplied through the environment, Node 22 for the dashboard build.", BODY), PageBreak()]

# ------------------------------------------------------------------ appendices
S += [p("Appendix A - Verification limits (what was NOT tested)", H1)] + bullets([
    "Live OpenAI / Gemini calls (chat, embeddings, vision, transcription): no credentials in the build environment. LLM-dependent code paths were exercised with scripted test doubles that verify orchestration, validation and fallbacks - not model quality.",
    "RAGAS: adapter plumbing tested against a stub module only. Cross-encoder reranker: dependency not installed; the fallback path is tested.",
    "Qdrant server mode: the server binary could not be executed in the sandbox; embedded mode passes the vector-backend contract and tenant-filter tests.",
    "Docker image build and docker compose start-up: no container daemon; the compose file parses and validates. GitHub Actions workflow: syntax-valid but not run; each command in it was run locally.",
    "Browser speech recognition and microphone capture; server-side Whisper (HTTP mocked).",
    "Load, soak and penetration testing; behaviour on corpora larger than the evaluation set."])
S += [p("Appendix B - Traceability from BRD v1", H1), table([["v1 requirement", "v2 treatment", "State"],
      ["FR-01 File upload", "FR-01 + validation, async jobs, visibility", status("T")], ["FR-02 Web ingestion", "FR-02 + DNS-rebinding-safe connect-by-IP", status("T")], ["FR-03 Extraction", "FR-03 + sections, tables, OCR", status("T")],
      ["FR-04 Chunking/indexing", "FR-04 + parent spans, tenant-scoped vectors", status("T")], ["FR-05 Exact search", "FR-05 unchanged semantics; page lists added", status("T")], ["FR-06 Semantic search", "FR-06 + FR-15 advanced RAG", status("T")],
      ["FR-07 Structured data", "FR-07 extended (sort, median, distinct, duplicates, comparison)", status("T")], ["FR-08 Routing", "FR-08 + FR-16 eight-agent supervisor", status("T")], ["FR-09 Evidence-based answers", "FR-09 + FR-17 verification", status("T")],
      ["FR-10 Cross-source", "FR-10", status("P", "conflict analysis needs an LLM")], ["FR-11 Conversation context", "FR-11 + persistent memory with rolling summary", status("T")], ["FR-12 Error handling", "FR-12", status("T")],
      ["FR-13 Re-ingestion/removal", "FR-13 + purge", status("T")], ["FR-14 API access", "FR-14 + OpenAPI + SSE", status("T")]], [48, 90, 32])]
S += [p("Appendix C - Configuration reference", H1), p("All settings are environment variables (prefix <font face='Courier'>MKA_</font>; provider keys <font face='Courier'>OPENAI_API_KEY</font>, <font face='Courier'>GEMINI_API_KEY</font>, <font face='Courier'>BRAVE_API_KEY</font>). The complete annotated list is in <font face='Courier'>.env.example</font>. "
                                                          "Production mode (<font face='Courier'>MKA_ENV=production</font>) refuses to start unless authentication is enabled, a 32+ character JWT secret is set, self-service signup and private-URL fetching are off, CORS has no wildcard and the database is PostgreSQL."),
      p("Appendix D - Delivered artefacts", H1)] + bullets(["Source code: <font face='Courier'>app/</font> (API, agents, RAG, ingestion, security, intelligence, evaluation), <font face='Courier'>frontend/</font> (React + TypeScript), <font face='Courier'>tests/</font>, <font face='Courier'>scripts/</font>.",
                                                            "Deployment: <font face='Courier'>Dockerfile</font>, <font face='Courier'>docker-compose.yml</font>, <font face='Courier'>.github/workflows/ci.yml</font>, <font face='Courier'>.env.example</font>.",
                                                            "Documentation: <font face='Courier'>README.md</font>, <font face='Courier'>docs/API.md</font>, <font face='Courier'>docs/openapi.json</font>, <font face='Courier'>docs/eval/</font> (latest evaluation report in JSON, Markdown and HTML)."])

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="Multi-Agent Knowledge Assistant - Updated BRD v2",
                        author="Multi-Agent Knowledge Assistant project", subject="Business Requirements Document v2.0")
doc.build(S, onFirstPage=header_footer, onLaterPages=header_footer)
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")
