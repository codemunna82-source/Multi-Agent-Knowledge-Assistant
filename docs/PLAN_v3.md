# Upgrade plan v3 — gap analysis against the "Enterprise AI Knowledge & Research Platform" master prompt

Baseline inspected on 30 Oct 2026 (166 backend tests). Final state: see docs/REQUIREMENTS_TRACE.md — all phases P1–P8 delivered.
**166 backend tests passing** (against real PostgreSQL 16 and Redis 7), ruff and `tsc --strict` clean.
Legend: ✅ implemented and tested · 🟡 partial · ❌ missing.

## 1. Where the repository stands

| Area | Master-prompt requirement | State today | Action |
|---|---|---|---|
| **Ingestion** | PDF, DOCX, TXT, MD, CSV, XLSX, JSON, URL, scanned PDF, PNG/JPG | ✅ all, with OCR (Tesseract) | — |
| | **XLS, HTML files** | ❌ | add loaders (xlrd, lxml/bs4) |
| | text + tables + metadata + page numbers | ✅ (pypdf + pdfplumber) | switch to **PyMuPDF** (speed, headings, page images), keep pypdf fallback |
| | **1,000+ page PDFs** | 🟡 page cap exists, never tested at scale | generate and ingest a 1,000-page PDF in the test-suite, record timings |
| | background jobs, progress, errors, delete+vectors | ✅ | — |
| | **duplicate detection, versioning, re-indexing** | 🟡 re-index only | content hash, duplicate refusal, versions (compare/rollback-safe), version list |
| **Document intelligence** | exact name/phrase search, counts, page results | ✅ | expose as dedicated paginated API |
| | entities (names, emails, phones, dates, companies, IDs) | 🟡 heuristic | keep; ORG detection tested |
| | **document classification** | ❌ | rule-based scorer + optional LLM with closed taxonomy |
| | long-document summaries | ✅ map-reduce | add **chapter/section summaries** and styles (short, detailed, executive) |
| | **comparison + change detection** | 🟡 tables only | text diff/alignment, version change detection |
| | table extraction | ✅ | — |
| | **event/date timeline** | ❌ | date+sentence extraction, chronological merge |
| | cross-document QA | 🟡 | source-diversity step in retrieval |
| | **contradiction detection** | ❌ | candidate-pair detector (numbers/negation) + optional LLM judgement |
| | multilingual, **Hindi + English** | 🟡 unicode retrieval, language detection | Hindi stop-words, Hindi routing keywords, tests |
| | **reports in PDF / DOCX / XLSX** | ❌ | report service with sources + timestamps |
| **RAG** | semantic, BM25, hybrid, rewrite, multi-query, HyDE, filters, parent-child, compression, rerank, corrective, Graph RAG | ✅ | — |
| | cross-encoder reranking | 🟡 optional dependency, model download blocked here | local-path loading; code path tested only if a model can be built offline |
| | **Self-RAG** | ❌ | retrieve-or-not decision, per-passage relevance, support/usefulness critique, bounded regeneration |
| | hypothetical text never evidence | ✅ by design (HyDE only embedded) | add explicit test |
| **Agents** | Supervisor, Document, Exact, Web, Summary, Verification, Response | ✅ | — |
| | **parallel execution**, **timeouts** | ❌ | LangGraph `Send` fan-out + merge; per-node timeouts |
| | **Data Analyst with SQL, charts, trends, anomalies** | 🟡 pandas ops only | safe SQL sandbox, charts, profile, anomalies, monthly/YoY |
| | **Comparison Agent** | ❌ | dedicated agent |
| | Verification: validate page/row citations, request more retrieval | 🟡 | citation validator, retry with widened retrieval |
| | Web: "approved sources" | 🟡 | per-tenant domain allow-list; separate web/document evidence sections |
| **Memory** | history, summaries, tenant isolation | ✅ | |
| | **user-controlled memory, relevant-context retrieval, reset, minimal sensitive storage** | ❌ | per-user memory switch, facts store, recall, PII redaction, reset/delete |
| **Security** | JWT, RBAC, tenancy, rate limit, audit, injection defences, upload validation | ✅ | |
| | **refresh tokens** | ❌ | rotating refresh tokens in httpOnly cookie, reuse detection |
| | **roles admin / manager / user** | 🟡 viewer/editor/admin | rename with data migration |
| | **document-level permissions** | 🟡 private/tenant | share with users/roles (restricted visibility) |
| | **retention policies** | ❌ | per-tenant retention + scheduled sweep |
| | secret management | 🟡 env only | `*_FILE` secrets support |
| **Background** | Redis queue, retries, progress | ✅ own queue | keep (see decision D1); add **scheduler** |
| **Database** | PostgreSQL for documents + permissions, **migrations**, indexes | 🟡 documents live on disk | **Alembic**, `documents`/`document_versions`/`document_permissions` tables |
| **API groups** | exact search, summary, comparison, analytics, web research, reports, pagination | ❌ (chat-only access) | add routers + `limit/offset` with `X-Total-Count` |
| **Frontend** | dashboard, library, exact search, comparison, analyst, reports, preview, themes | 🟡 | build the missing screens, theme toggle, PDF page preview |
| **Evaluation / observability** | citation accuracy, agent success, failed tool calls, OpenTelemetry/LangSmith | 🟡 | metrics, `/metrics` (Prometheus), OTel spans; LangSmith env wiring |
| **DevOps** | migrations in deploy, backup/recovery docs | 🟡 | `alembic upgrade head` in start-up/compose, backup runbook |
| **KG / multimodal** | relationship extraction, chart/diagram extraction | 🟡 heuristic graph; captions for images | optional LLM triple extraction; vision-LLM chart reading (scripted-model tests only) |

## 2. Decisions and trade-offs (made up-front, not discovered later)

* **D1 — Celery.** The existing Redis queue + worker is tested (idempotent claim, bounded retries, crash re-delivery, separate worker process). Replacing it with Celery adds a dependency and no capability the requirement needs ("Celery *or an appropriate background job system*"). We keep it and add a scheduler for periodic jobs.
* **D2 — PyMuPDF** is used when installed (much faster, gives headings and page images) with **pypdf as fallback**. Note PyMuPDF is AGPL/commercial-licensed — a legal decision for operators; documented.
* **D3 — PaddleOCR is not added** (very large model downloads); Tesseract stays.
* **D4 — Cross-encoder.** Hugging Face is unreachable from this environment, so no real model can be downloaded; the loader accepts a local path, and only the code path (not ranking quality) can be verified here.
* **D5 — LangSmith.** `api.smith.langchain.com` is unreachable here; LangSmith is wired through environment variables only and is **untested**. OpenTelemetry and Prometheus are implemented and tested locally.
* **D6 — Graph storage.** NetworkX (in-process, rebuilt per accessible-document set) instead of Neo4j: no extra service, independently testable; large graphs would need a graph DB.
* **D7 — SQL sandbox.** Read-only, single-statement `SELECT` executed in an in-memory SQLite database loaded from the spreadsheet, guarded by SQLite's *authorizer* (whitelist of operations/functions), a row limit and an execution-time limit — no generated Python is ever executed.
* **D8 — Role mapping.** `viewer→user`, `editor→manager`; `manager` may ingest, share, evaluate, generate reports and see tenant audit summaries for own documents; `admin` manages users/retention/settings.
* **D9 — Test honesty.** LLM-dependent behaviour is tested with scripted test doubles (orchestration, validation, fallbacks); live-provider quality, a Qdrant *server*, Docker builds and CI execution remain untested unless stated otherwise.

## 3. Phases (each ends with a green test run and a commit)

1. **P1 Data foundation** — Alembic baseline + v3 migration; PostgreSQL document registry/versions/permissions; roles; refresh tokens; tenant settings; pagination.
2. **P2 Ingestion** — PyMuPDF, XLS, HTML, duplicate detection, versioning, 1,000-page test, page preview, classification, timeline.
3. **P3 Data Analyst** — profile, SQL sandbox, charts, anomalies, trends, comparisons, API.
4. **P4 Comparison/Self-RAG/verification** — Comparison Agent, contradictions, Self-RAG, citation validation, widened-retrieval retry, diversity, Hindi.
5. **P5 Orchestration & operations** — parallel supervisor, timeouts, web allow-list, metrics/OTel, scheduler, retention.
6. **P6 Reports & APIs & memory** — PDF/DOCX/XLSX reports, remaining API groups, user-controlled memory.
7. **P7 Frontend** — all screens, themes, page preview, charts, tests, end-to-end.
8. **P8 Evaluation, docs, BRD, ZIP** — extended metrics/datasets, CI, runbooks, BRD, final verification.
