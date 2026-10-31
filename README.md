# Multi-Agent Knowledge Assistant v3 — Enterprise AI Knowledge & Research Platform

A multi-tenant platform for working with large, mixed-format document collections: upload files (PDF, DOCX, TXT, MD, CSV, XLSX/XLS, JSON, HTML, images, URLs), then search exactly, ask questions,
summarise, compare versions, find contradictions, analyse spreadsheets (pandas + sandboxed read-only SQL, charts, trends, outliers) and generate PDF/DOCX/XLSX reports — every answer with
**validated citations** (file, version, page, sheet/row, section, URL). A LangGraph supervisor routes to specialised agents (exact search, document/RAG with optional Self-RAG, data analyst,
summary, comparison, web research), runs compound questions in parallel, and a verification step refuses to ship what it cannot ground.

* Business requirements (v2.1, implemented vs partial vs not): [`docs/Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf`](docs/Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf)
* [`docs/REQUIREMENTS_TRACE.md`](docs/REQUIREMENTS_TRACE.md) requirement → code → test · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) diagrams · [`docs/OPERATIONS.md`](docs/OPERATIONS.md) deploy, monitor, back up, retention
* [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) measured numbers and limits · [`docs/API.md`](docs/API.md) / [`docs/openapi.json`](docs/openapi.json) (75 operations) · [`docs/eval/`](docs/eval) evaluation reports

> **Honest status.** Everything marked *tested* was executed in the build environment. Not executed: live OpenAI/Gemini calls (LLM paths are tested with scripted doubles), a Qdrant *server*,
> Docker build / Compose / GitHub Actions, RAGAS, a cross-encoder model, LangSmith, an OTLP collector. See [Implemented vs partial vs pending](#implemented-vs-partial-vs-pending).

## Quick start (no API keys, no external services)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
sudo apt-get install -y tesseract-ocr          # only needed for OCR (MKA_OCR_ENABLED=true) and image files
cp .env.example .env                           # defaults run fully offline (SQLite, local vectors, hash embedder, no LLM)
uvicorn app.main:app --reload                  # http://localhost:8000  (API docs: /docs)

# optional: the React dashboard 
cd frontend && npm ci && npm run build && cd ..   # served by FastAPI from frontend/dist
```

Defaults run with authentication **off** (a banner says so). For anything shared, turn it on:

```bash
export MKA_AUTH_ENABLED=true MKA_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
python -m app.cli create-tenant --name "ACME" --email admin@acme.com      # prompts for the password
```

### Real answers instead of extracted passages

The offline defaults are deliberately dependency-free: the `hash` embedder is *lexical* (no paraphrase recall) and without an LLM answers
are verbatim extracted sentences. For real semantic recall and generated, cited answers:

```bash
export MKA_EMBEDDING_PROVIDER=openai MKA_LLM_PROVIDER=openai OPENAI_API_KEY=sk-...   # or gemini + GEMINI_API_KEY
```
Re-index existing documents after changing the embedder (the UI marks them *needs re-index*).

### Docker (API + worker + scheduler + PostgreSQL + Redis + Qdrant)

```bash
cp .env.example .env     # set MKA_JWT_SECRET (>=32 chars), optional provider keys
export POSTGRES_PASSWORD=$(openssl rand -hex 16)
docker compose up --build
docker compose exec api python -m app.cli create-tenant --name "ACME" --email admin@acme.com
```
`MKA_ENV=production` refuses insecure settings and runs Alembic migrations at start. *The compose file and Dockerfile were not built or run here (no container runtime).* See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Highlights

| Area | What you get |
|---|---|
| Ingestion | PyMuPDF (pypdf fallback), OCR, XLS/HTML, tables, headings; 1,000 pages in ~6 s; duplicate refusal, versions (+ what changed, rollback), classification, timeline, page previews |
| Search / RAG | exact full-corpus counts with pages; hybrid BM25 + vectors, rewrite, multi-query, HyDE, parent-child, compression, rerank, corrective, **Self-RAG**, Graph RAG, Hindi + English |
| Agents | supervisor with **parallel fan-out**, per-node timeouts and retries, **Comparison** (diff, versions, contradictions), **Data Analyst** (pandas, SQL sandbox, charts), Web (approved domains, separate evidence), Verification (citations checked against stored text, widened retry) |
| Reports | summary, executive, comparison, research, analytics, exact-search, evaluation → PDF / DOCX / XLSX with sources and timestamps |
| Security | JWT + rotating httpOnly refresh token, roles user/manager/admin, tenant isolation, document sharing, audit, rate limits, injection/SSRF defences, retention + erasure, user-controlled memory |
| Operations | PostgreSQL + Alembic, Redis queue, scheduler, `/metrics`, OpenTelemetry, backup/restore scripts |
| Learn | **Learn lab**: ablate/compare retrieval techniques, see the LangGraph run step by step, real LangChain objects on your documents — [`docs/LEARNING.md`](docs/LEARNING.md); **✨ Auto** lets a graph node pick the best retrieval setting per question |
| UI | ChatGPT-style chat (character-by-character reveal), 14+ screens (dashboard, library, chat, citation preview, exact search, comparison, analyst, reports, history, settings, admin, …), light/dark |

Measured on 4 vCPU (offline config): 1,000-page PDF ingest 5.6 s · exact search 0.1 s with the correct count · complete `/ask` ~90 ms · 200,000-row CSV profile 1.3 s, SQL group-by 65 ms.

## Using it

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' -d '{"email":"admin@acme.com","password":"..."}' | jq -r .access_token)
H="Authorization: Bearer $TOKEN"; W="X-Session-ID: hr-team"
curl -H "$H" -H "$W" -F files=@handbook.pdf "localhost:8000/sources/upload?async=true"
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/search/exact -d '{"term":"Anjali Rao"}'
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/ask -d '{"question":"What changed in policy.txt?"}'
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/analytics/ask -d '{"question":"Show the monthly revenue trend"}'
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/reports -d '{"kind":"summary","format":"pdf"}'
```

## Testing

```bash
ruff check . && pytest        # set MKA_TEST_PG_URL / MKA_TEST_REDIS_URL to include the PostgreSQL and Redis tests
cd frontend && npm ci && npm run typecheck && npm test && npm run build
cd frontend && NODE_PATH=$(npm root -g) node e2e/smoke.mjs        # real server + headless Chromium
MKA_SMOKE_PG_URL=... MKA_SMOKE_REDIS_URL=... python scripts/prod_smoke.py
python -m app.eval run --sample --compare --out eval_report; python -m app.eval run --sample --extended --out eval_report_ext
python scripts/benchmark.py; python scripts/gen_api_docs.py; python docs/build_brd.py
```
Last run (31 Oct 2026): **351 pytest** (real PostgreSQL 16 + Redis 7) · **49 Vitest** · **19/19 Playwright steps** · **12/12 production-smoke checks** · ruff, `tsc --strict`, `alembic check` clean.
Evaluation is synthetic and offline (hash embedder, no LLM): it is a regression guard, not an accuracy benchmark; faithfulness/relevancy are lexical/embedding proxies.

## Implemented vs partial vs pending

**Implemented and tested**: everything in [`docs/REQUIREMENTS_TRACE.md`](docs/REQUIREMENTS_TRACE.md) marked ✅.
**Partial** (what was not exercised): cross-document QA (no multi-hop); Hindi (PDF reports do not shape Devanagari; no multilingual embedder measured); cross-encoder reranker; Qdrant server; web search provider; vision captions and any live LLM behaviour; secret management (env + `*_FILE`, no vault); LangSmith and OTLP delivery; Docker/Compose/CI definitions (never run).
**Not implemented**: SSO/OIDC/MFA · graph database and relation-type extraction · reading values from chart images · object storage · Celery (built-in Redis queue used) · PaddleOCR · load/penetration testing · validation on a real customer corpus.
Licence note: PyMuPDF is AGPL-3.0/commercial; `MKA_PDF_ENGINE=pypdf` avoids it.
