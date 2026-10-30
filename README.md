# Multi-Agent Knowledge Assistant v2

A multi-tenant **knowledge intelligence platform**: upload documents (or point at public web pages), ask questions in natural language,
and get answers with **verifiable citations** — file, page, sheet/row, section or URL. An eight-agent LangGraph supervisor routes each
question to exact search, advanced hybrid RAG, controlled spreadsheet analysis, summarisation/document intelligence or the web, and a
verification step refuses to ship answers it cannot ground.

* Business requirements: [`docs/Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf`](docs/Multi_Agent_Knowledge_Assistant_Updated_BRD_v2.pdf)
* API reference: [`docs/API.md`](docs/API.md) · OpenAPI: [`docs/openapi.json`](docs/openapi.json) · Swagger UI at `/docs`
* Latest evaluation report: [`docs/eval/eval_report.md`](docs/eval/eval_report.md) (HTML/JSON alongside)

> **Honest status.** See [Implemented vs pending](#implemented-vs-pending). Everything marked *tested* was executed in the build
> environment; anything that needs a live LLM provider, a Qdrant *server*, or a container runtime was **not** exercised and is listed as such.

## Quick start (no API keys, no external services)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
sudo apt-get install -y tesseract-ocr          # only needed for OCR (MKA_OCR_ENABLED=true) and image files
cp .env.example .env                           # defaults run fully offline (SQLite, local vectors, hash embedder, no LLM)
uvicorn app.main:app --reload                  # http://localhost:8000  (API docs: /docs)

# optional: the React dashboard (otherwise the classic single-page UI is served at /classic and as a fallback at /)
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

### Docker (API + worker + PostgreSQL + Redis + Qdrant)

```bash
cp .env.example .env     # set MKA_JWT_SECRET (>=32 chars), optional provider keys
export POSTGRES_PASSWORD=$(openssl rand -hex 16)
docker compose up --build
docker compose exec api python -m app.cli create-tenant --name "ACME" --email admin@acme.com
```
`MKA_ENV=production` (set by the compose file) makes the API **refuse to start** with insecure settings (auth off, weak/missing JWT secret,
signup enabled, private-URL fetching, wildcard CORS, SQLite). *The compose file validates (`docker compose config`), but the image build and
stack start-up could not be executed in the build environment (no container daemon).*

## Architecture

```
React dashboard ──► FastAPI (JWT, RBAC, rate limits, audit, request IDs)
                      │
                      ├─ sources / jobs ──► queue (in-process | Redis) ──► ingestion workers
                      │                       validate → extract (OCR, tables, sections) → chunk → embed → atomic commit
                      │
                      └─ /ask, /ask/stream ──► LangGraph supervisor ──► Exact | Semantic | Document Search | SQL/Pandas | Summarization | Web
                                                                         └► Verification (bounded retries) ► Final Response
   Advanced RAG: rewrite · multi-query · HyDE · BM25+vector (RRF) · metadata filters · parent-child · rerank · compression · corrective loop
   Stores: PostgreSQL (identity, audit, jobs, conversations, eval, LangGraph checkpoints) · Qdrant | Chroma | local (vectors) · Redis (limits, queue) · data volume (documents)
```

### Project structure

```
app/
  main.py                 ASGI entry (uvicorn app.main:app)          cli.py     create-tenant
  config.py               typed settings (env), production validator  db.py      SQLAlchemy models (PostgreSQL/SQLite)
  api/                    app factory, deps (auth, workspace, rate limit, audit), routers: auth sources jobs chat intel evaluation admin
  agents/                 LangGraph: graph.py (StateGraph wiring) · nodes.py (all agents) · routing.py (supervisor) · tools.py (closed tool registry)
                          assistant.py (checkpointer, streaming, memory) · verification/final in nodes.py · followups.py · intel_ops.py · summarize.py
  rag/                    pipeline.py (retrieve → fuse → parents → rerank → compress → grade → corrective) · steps.py (techniques) · index.py (BM25, ACL) · options.py
  ingestion/              loaders.py (PDF/OCR/DOCX/XLSX/CSV/MD/JSON/images) · chunking.py · web.py (SSRF-safe fetch)
  tools/                  exact.py (full-corpus search) · tabular.py (pandas plans) · summarise.py (map-reduce)
  intel/                  entities.py · graph.py (knowledge graph / Graph RAG) · questions.py · language.py
  security/               auth.py (JWT, bcrypt, RBAC) · ratelimit.py · audit.py · injection.py · files.py
  eval/                   metrics.py · runner.py · sample.py (synthetic corpus) · report.py · ragas_adapter.py · __main__.py
  jobs.py worker.py       background ingestion · service.py (ingest pipeline) · storage.py (tenant-scoped store, vector backends)
  providers.py            embeddings (hash/OpenAI/Gemini), LLMs, usage + cost metering · memory.py (rolling conversation memory) · web_search.py
frontend/                 Vite + React + TypeScript dashboard (src/, Vitest tests, e2e/smoke.mjs)
tests/                    pytest suites (see Testing)         scripts/   gen_api_docs.py, prod_smoke.py
docs/                     BRD v2 PDF (+ build_brd.py), API.md, openapi.json, eval/ report
Dockerfile docker-compose.yml .github/workflows/ci.yml .env.example requirements*.txt pyproject.toml
```

### Key design decisions

| Decision | Why |
|---|---|
| Counts and spreadsheet numbers are computed by code over the **complete** data | vector top-K cannot count; an LLM must never be the source of a figure |
| Closed tool registry, no code/SQL execution anywhere | documents and prompts are untrusted; the only "query language" is a validated JSON plan executed with pandas |
| Verification agent + bounded retries + verbatim fallback | generated answers must cite, may not introduce numbers absent from evidence, and cannot loop forever |
| Chunks never cross page/sheet/table/section boundaries | a citation must point at exactly one location |
| Tenant + workspace are part of every storage address; Qdrant filters are mandatory | isolation must not depend on callers remembering a filter |
| URL fetch resolves once and connects to the vetted IP with verified SNI | closes the DNS-rebinding gap between check and use |
| Every LLM step has a deterministic fallback and validated output | features degrade, requests don't fail |

## Using it

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' -d '{"email":"admin@acme.com","password":"..."}' | jq -r .access_token)
H="Authorization: Bearer $TOKEN"; W="X-Session-ID: hr-team"          # W selects the workspace inside your tenant

curl -H "$H" -H "$W" -F files=@handbook.pdf -F files=@sales.xlsx "localhost:8000/sources/upload?async=true"   # 202 + job ids
curl -H "$H" -H "$W" localhost:8000/jobs/<job_id>                                                          # progress
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/ask \
     -d '{"question":"Does Anjali appear in the handbook?"}'                    # count, pages, excerpts
curl -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/ask \
     -d '{"question":"What is our leave policy?","retrieval":{"mode":"hybrid","multi_query":true,"filters":{"kinds":["pdf"],"page_min":2}}}'
curl -N -H "$H" -H "$W" -H 'content-type: application/json' localhost:8000/ask/stream -d '{"question":"Summarize handbook.pdf"}'   # SSE
```
Example questions: *"Does Anjali appear in this 1000-page PDF?"* (exact) · *"Which employee has the highest sales?"* · *"Are there duplicate emails?"* ·
*"Compare left.csv and right.xlsx"* · *"Summarize report.pdf"* · *"How is X related to Y?"* · *"Extract the tables from contract.docx"* · *"Generate questions about policy.md"*.

## Testing

```bash
ruff check .                                                # lint
pytest                                                      # backend; PostgreSQL/Redis integration tests are skipped unless these are set:
MKA_TEST_PG_URL=postgresql+psycopg2://postgres:postgres@localhost/mka_test MKA_TEST_REDIS_URL=redis://localhost:6379/0 pytest
cd frontend && npm test && npm run typecheck && npm run build   # Vitest, strict TypeScript, production bundle
cd frontend && NODE_PATH=$(npm root -g) node e2e/smoke.mjs      # real server + browser (needs: npm i -g playwright; npx playwright install chromium)
MKA_SMOKE_PG_URL=... MKA_SMOKE_REDIS_URL=... python scripts/prod_smoke.py   # separate API + worker processes, production-mode config
python -m app.eval run --sample --compare --out eval_report     # evaluation report (json/md/html)
python scripts/gen_api_docs.py && python docs/build_brd.py      # regenerate API docs / BRD
```
Latest run (30 Oct 2026): **166 passed pytest** · **19 passed Vitest** · **12/12 Playwright steps** · **12/12 production-smoke checks** · ruff and `tsc --strict` clean.

### Evaluation (synthetic corpus, offline: hash embedder, no LLM)

| Recall@5 | Precision@5 | MRR | Exact-count acc. | Table acc. | Abstention acc. | Latency p50 / p95 |
|---|---|---|---|---|---|---|
| 90.9% | 18.2% | 0.909 | 100.0% | 100.0% | 75.0% | 9 / 28 ms |

The set is small and synthetic: it catches regressions and compares strategies; it is **not** a real-world accuracy benchmark. Faithfulness and
relevancy shown in reports are lexical/embedding *proxies*; LLM-judge and RAGAS scores need a configured model (not measured here). Hard
paraphrases fail with the offline embedder — by design, and listed in the report.

## Security summary

JWT (bcrypt, revocation) · RBAC (viewer/editor/admin) · tenant + workspace isolation · private documents · rate limits (in-process or Redis) ·
append-only audit log (hashes, never question/document text) · upload validation (magic bytes, zip-bomb/macro checks) · prompt-injection defences
(scan, data fences, closed tools, output guard, optional exclude policy) · SSRF/DNS-rebinding protection · secrets only from the environment and masked in the
admin API · production start-up validator · deletion (source, conversation, workspace, tenant purge). Residual risks are in BRD §13.

## Implemented vs pending

**Implemented and tested**: multi-format ingestion (PDF, CSV, XLSX, DOCX, TXT, MD, JSON, URLs) with page/sheet/row/section/URL/document-ID metadata · OCR for scanned PDFs and images ·
PDF/DOCX/HTML/spreadsheet table extraction · semantic, BM25 and hybrid search · query rewriting, multi-query, HyDE, metadata filtering, parent-child retrieval, contextual compression,
reranking (lexical, LLM), corrective RAG (bounded) — *HyDE/LLM-rerank/LLM-compress/LLM-grade with a scripted model* · full-corpus exact search with counts, pages, excerpts · controlled table analysis
(filter, sort, group, sum, mean, median, min/max, distinct, duplicates, comparison) · supervisor + 8 agents with typed state, conditional edges, tool registry, checkpointing (memory/SQLite/PostgreSQL),
bounded retries, session memory · verification and output guard · entity extraction, table extraction, question generation, follow-ups, summaries, cross-document comparison · multilingual
retrieval (Unicode tokenisation, language detection, cross-lingual query translation *with a scripted model*) · knowledge graph + Graph RAG · SSE streaming · PostgreSQL, Redis, background workers ·
Qdrant (embedded mode) and ChromaDB · JWT, RBAC, multi-tenancy, document ACL, rate limiting, audit, deletion · prompt-injection and SSRF protection · evaluation harness, reports, dashboard ·
React/TypeScript dashboard · Dockerfile/compose/CI definitions (syntax-validated).

**Implemented, only partly tested** (what was not exercised): live OpenAI/Gemini behaviour (chat, embeddings, vision captions, Whisper) · RAGAS (stub-tested adapter) · cross-encoder reranker ·
Qdrant *server* · browser speech recognition · provider-side token streaming (answer text is streamed after generation) · multimodal beyond OCR/captions of image files.

**Pending**: Docker image build and compose run, GitHub Actions run · Alembic migrations · object storage for documents (today: shared volume) · OpenSearch/PG full-text for very large corpora ·
OIDC/SSO, MFA, refresh tokens, httpOnly-cookie sessions · automatic retention policies · images embedded inside PDFs · relation-type extraction for the knowledge graph · load/penetration testing ·
validation on a real corpus with real models (BRD AC-15).

## Operations notes

* The API and worker must share `MKA_DATA_DIR` (uploads are staged there). Run one worker per CPU-heavy ingestion slot; duplicate delivery is safe.
* Behind a reverse proxy run uvicorn with `--proxy-headers` and restrict who can set `X-Forwarded-For`; per-IP limits (login) otherwise see the proxy address.
* `MKA_CHECKPOINT_BACKEND=postgres` keeps agent checkpoints in the same PostgreSQL; `sqlite` is fine for a single node.
* Change the embedding model ⇒ re-index sources (they are flagged). Deleting a source removes text, chunks, vectors and the original.
