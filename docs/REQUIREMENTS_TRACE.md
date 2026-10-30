# Requirements trace – master prompt v3 → implementation → evidence

Legend: ✅ implemented and exercised by an automated test · 🟡 implemented, but part of it could **not** be exercised here (the gap is stated) · ❌ not implemented.
"Scripted model" means the LLM path was tested with a deterministic test double (orchestration, validation, fallbacks) – **no live OpenAI/Gemini call was made in any test**.

## Ingestion

| Requirement | Status | Where / evidence |
|---|---|---|
| PDF, DOCX, TXT, MD, CSV, XLSX, **XLS**, JSON, **HTML**, URLs | ✅ | `ingestion/loaders.py`, `ingestion/web.py` · `test_ingestion_v3.py` (xls, html, encodings), `test_ingestion.py`, `test_web_and_api.py` |
| Scanned PDF, PNG/JPG (OCR) | ✅ Tesseract (PaddleOCR not added – decision D3) | `test_phase2_ingestion.py::test_scanned_pdf_rejected_without_ocr_and_read_with_ocr`, `::test_image_upload_is_ocr_indexed` |
| Text, tables, metadata, page numbers; headings; document properties | ✅ PyMuPDF engine with pypdf fallback; tables only where a PDF has ruled lines (borderless tables are not detected) | `test_ingestion_v3.py::test_pdf_properties_and_ruled_table`, `test_phase2_ingestion.py::test_table_extraction_pdf_docx_xlsx_html` |
| 1,000+ page PDFs | ✅ 1,000 pages ingest in ~5.6 s; counts exact | `test_large_documents.py`, `docs/PERFORMANCE.md` |
| Background jobs, progress, errors, retries | ✅ own Redis/in-process queue (not Celery – decision D1) | `test_phase2_platform.py`, `scripts/prod_smoke.py` (separate worker process) |
| Encodings, malformed/corrupt files | ✅ | `test_ingestion_v3.py::test_corrupt_files_fail_cleanly`, `test_phase2_ingestion.py` |
| Duplicate detection, versioning, re-indexing | ✅ sha256 identity, versions kept (not searched), rollback `make-current`, concurrency-safe | `test_foundation.py` |
| Delete with vectors; metadata (page, sheet, row, URL) | ✅ | `test_foundation.py`, `test_search.py` |

## Document intelligence

| Requirement | Status | Where / evidence |
|---|---|---|
| Exact name / keyword / phrase search over the full text, counts, pages | ✅ `POST /search/exact`, chat exact route | `test_search.py`, `test_reports_memory.py::test_exact_search_api_*`, 1,000-page test |
| Entity extraction | ✅ heuristic (+ LLM values kept only if verbatim in the text – scripted model) | `test_intelligence.py` |
| Document classification | ✅ keyword/structure scorer; optional LLM restricted to a closed taxonomy (scripted model) | `test_ingestion_v3.py` |
| Long-document, chapter, section summaries (short / detailed / executive) | ✅ map-reduce over every unit; extractive without an LLM | `test_reports_memory.py::test_summaries_api_*` |
| Comparison and change detection (documents, versions) | ✅ sentence alignment with number changes | `test_compare.py`, `::test_compare_and_changes_api` |
| Table extraction | ✅ | see Ingestion |
| Event / date timeline | ✅ ISO, text dates, quarters, ambiguity flag | `test_ingestion_v3.py` |
| Cross-document QA | 🟡 retrieval is diversified so every relevant document is represented; there is no multi-hop reasoning | `test_verification_selfrag.py::test_cross_document_*` |
| Contradiction detection | ✅ heuristic candidates (numbers, negation, antonyms); LLM judge confirms (scripted model) | `test_compare.py` |
| Multilingual incl. Hindi + English | 🟡 Hindi tested end to end (exact, retrieval, spreadsheet questions with Hindi headers, routing keywords, summary, contradiction, DOCX/XLSX reports); semantic quality with a real multilingual embedder not measured; **PDF reports do not shape Devanagari** | `test_verification_selfrag.py::test_hindi_*`, `eval/extended.py` |
| Automatic reports PDF / DOCX / XLSX with sources and timestamps | ✅ summary, executive, comparison, research, analytics, exact-search, evaluation | `test_reports_memory.py`, `test_evaluation.py` |

## RAG

| Requirement | Status | Evidence |
|---|---|---|
| Semantic, BM25, hybrid, rewrite, multi-query, HyDE (never evidence), metadata filters, parent-child, compression | ✅ (LLM-dependent steps with a scripted model) | `test_rag.py` |
| Cross-encoder reranking | 🟡 code path and local-model loading exist; Hugging Face is unreachable here, so no model was run | – |
| **Self-RAG** (retrieve-or-not, passage relevance, support/usefulness critique, bounded regeneration) | ✅ deterministic critique + scripted-model judgements | `test_verification_selfrag.py` |
| Corrective RAG, Graph RAG | ✅ | `test_rag.py`, `test_intelligence.py` |
| Deduplication, thresholds, top-K, citations | ✅ | `test_rag.py` |
| Qdrant (prod) / Chroma (dev) | 🟡 Qdrant tested in embedded mode only – a Qdrant **server** was never started; Chroma ✅ | `test_phase2_platform.py`, `test_web_and_api.py::test_chroma_backend` |

## Agents and routing

| Requirement | Status | Evidence |
|---|---|---|
| Supervisor with parallel coordination and retries | ✅ LangGraph `Send` fan-out + merge; concurrency measured; branch failures isolated | `test_operations.py::test_parallel_*` |
| Document, Exact, Summary, Comparison, Verification, Response agents | ✅ | `test_agents.py`, `test_compare.py`, `test_verification_selfrag.py` |
| Data Analyst: Pandas + **SQL**, charts, trends, duplicates, anomalies | ✅ sandboxed read-only SQL; NL→SQL by a model is validated by the same sandbox (scripted model) | `test_analytics.py`, `test_tabular.py`, `test_data_ops.py` |
| Web Research (approved sources, separate web evidence) | ✅ per-tenant allow-list, redirect check, `origin=web` citations, tested with a mock transport; a real search provider (SearXNG/Brave) was not called | `test_operations.py::test_web_allow_list_*` |
| Verification: validate page/row citations, request more retrieval | ✅ citations checked against stored text; first retry widens retrieval | `test_verification_selfrag.py`, `test_agents.py` |
| Typed state, conditional routing, checkpoints, retry limits, timeouts | ✅ | `test_agents.py`, `test_operations.py::test_node_timeout_*` |
| Intent routing without vector search for counts / numbers | ✅ | `test_agents.py::test_supervisor_rules_route` |
| Charts and Excel report generation | ✅ SVG specs (UI), PNG (matplotlib), native XLSX charts | `test_analytics.py`, `test_reports_memory.py` |

## Knowledge graph and multimodal

| Requirement | Status | Note |
|---|---|---|
| Entity extraction, graph retrieval | ✅ NetworkX co-mention graph | relation **types** are not inferred (pending) |
| Neo4j / graph database | ❌ (decision D6) | in-process graph rebuilt per accessible document set |
| Image / chart / table / visual QA | 🟡 OCR ✅; vision captions through an LLM tested with a scripted model; reading values out of chart images is not implemented | `test_phase2_ingestion.py::test_image_vision_caption_pipeline` |

## Memory

✅ conversation history and rolling summary, session memory, **opt-in notes** that are recalled only when switched on and are never citations, incognito questions/conversations, reset/delete, tenant isolation, sensitive-data refusal and optional masking (pattern-based, not a guarantee) – `test_reports_memory.py` (memory tests).

## Security

| Requirement | Status | Evidence |
|---|---|---|
| JWT + **refresh tokens** (rotation, reuse detection, httpOnly cookie) | ✅ | `test_foundation.py` |
| Roles admin / manager / user (legacy names migrated) | ✅ | `test_foundation.py`, `test_auth_tenancy.py` |
| Multi-tenant isolation; **document-level permissions** | ✅ | `test_auth_tenancy.py::test_tenant_isolation_everywhere`, `test_foundation.py` (sharing) |
| Upload validation and limits; rate limiting; audit | ✅ | `test_security_units.py`, `test_ingestion.py`, `test_auth_tenancy.py` |
| Secret management | 🟡 environment + `*_FILE` secrets (tested); no vault/KMS integration | `test_foundation.py` |
| Prompt-injection protection, safe tool execution | ✅ heuristic scan, data fences, closed tools, SQL authorizer | `test_rag.py`, `test_analytics.py` |
| **Data deletion and retention policies** | ✅ per-tenant retention enforced by the scheduler; erase user / tenant / memory | `test_operations.py`, `test_reports_memory.py` |
| SSO / OIDC, MFA | ❌ | |

## Background, database, API

✅ Redis + worker, status/retry/progress, **scheduled tasks** (`python -m app.scheduler`, leader lock) · PostgreSQL with Alembic migrations and indexes (migrations verified against the models and on an empty PostgreSQL) · Qdrant/Chroma/Redis.
API groups: auth, users/roles, documents, ingestion jobs, chat + streaming, exact search, summaries, comparison, analytics, web research, reports, memory, evaluation, admin/audit – see [`API.md`](API.md) (75 operations). Pagination (`limit`/`offset`, `X-Total-Count`) on sources, jobs, conversations, reports, memory notes, users, audit, eval runs and exact-search matches. OpenAPI: [`openapi.json`](openapi.json).

## Frontend (React + TypeScript, light/dark)

✅ all 14 screens: login/registration · dashboard · upload · library (versions, sharing, class) · ingestion progress · chat with streaming · citations + PDF page preview · exact search results · comparison · data analyst (charts) · generated reports · conversation history · user/role management · settings/admin. Vitest (component tests with mocked HTTP) and a Playwright run against the real server and headless Chromium. The layout has responsive CSS rules but was only exercised at desktop width.

## Evaluation and observability

| Requirement | Status | Note |
|---|---|---|
| Recall@K, Precision@K, MRR, nDCG, latency, tokens, cost | ✅ | `test_evaluation.py` |
| Faithfulness, answer relevancy | 🟡 lexical/embedding **proxies**; LLM-judge needs a model (scripted test); RAGAS adapter tested with a stub module – `ragas` itself is not installed | |
| **Citation accuracy**, **agent execution success**, **failed tool calls** | ✅ | `test_evaluation.py` (v3 section) |
| Dataset + regression tests (incl. Hindi, comparison, contradictions, analytics, parallel) | ✅ | `eval/extended.py` |
| Reports PDF / DOCX / XLSX | ✅ | `GET /eval/runs/{id}/report.{pdf,docx,xlsx}` |
| OpenTelemetry | ✅ spans verified with an in-memory exporter; OTLP delivery to a collector not tested | |
| LangSmith | 🟡 environment wiring only; no network access to LangSmith from the build environment | |
| Prometheus `/metrics` | ✅ | `test_operations.py` |

## DevOps

| Requirement | Status |
|---|---|
| Dockerfile, Compose, `.env.example`, CI workflow | 🟡 written and syntax-checked; **no Docker daemon and no GitHub Actions run were available** – never built/executed |
| Migrations, health checks, JSON logging, monitoring | ✅ |
| Deployment and backup/recovery documentation | ✅ `OPERATIONS.md`; `scripts/backup.sh` + `restore.sh` were run against PostgreSQL (dump → empty database → restore → login and question answered) |
| Production-shaped run (API + worker as separate processes, PostgreSQL, Redis) | ✅ `scripts/prod_smoke.py` |
