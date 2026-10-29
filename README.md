# Multi-Agent Knowledge Assistant

Upload documents or give a public URL, ask questions in plain language, and get short answers with
**verifiable citations** (file, PDF page, sheet/row, JSON path, URL). Implements the BRD v1.0
(FastAPI + LangGraph, hybrid retrieval, exact counting, controlled table analysis).

## Run

```bash
pip install -r requirements.txt
cp .env.example .env            # optional; works offline with defaults
uvicorn app.main:app --reload   # web UI: http://localhost:8000/   API docs: /docs
pytest
```

```bash
curl -F "files=@report.pdf" -F "files=@sales.xlsx" localhost:8000/sources/upload
curl -X POST localhost:8000/sources/url -H 'content-type: application/json' -d '{"url":"https://example.com"}'
curl -X POST localhost:8000/ask -H 'content-type: application/json' -d '{"question":"Which employee has the highest sales?"}'
```

Send `X-Session-ID: <id>` to keep data and conversation isolated per session (default: `default`).
**This is not authentication** — put a real auth layer in front before multi-user use (BRD: out of scope).

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | status, active providers, usage counters |
| `POST /sources/upload` | one or more files → per-file `ready`/`failed` + clear error |
| `POST /sources/url` | ingest a public http(s) page |
| `GET /sources`, `GET /sources/{id}` | list / inspect (warnings, pages, tables, `needs_reindex`) |
| `POST /sources/{id}/reindex` | re-extract & re-embed (URLs are re-fetched) |
| `DELETE /sources/{id}` | removes text, chunks and vectors together |
| `POST /ask` | `question`, optional `source_ids`, `top_k`, `case_sensitive`, `whole_word` |
| `DELETE /session` | wipe all sources + history of the session |

## How a question is answered (LangGraph)

`classify → exact | semantic | tabular | summarise | compare | combined → answer`

| Question | Route | Done by |
|---|---|---|
| "Does John Smith appear…?", IDs, quoted phrases | `exact` | regex scan of the **entire** extracted text; count + page/row locations |
| "Where does clause 8 appear?" | `combined` | exact + semantic |
| "Which employee has the highest sales?" | `tabular` | whitelisted pandas plan (count/sum/mean/min/max, filter, group) |
| "Summarise this report" | `summarise` | map-reduce over every chunk |
| "Compare the policy with the tracker" | `compare` | per-source retrieval, side by side |
| anything else | `semantic` | vector + BM25 (RRF), relevance gate |

Design guarantees:
- **Counts and spreadsheet numbers are computed by code, never by the LLM.** Matching rules (case, whole-word, boundary behaviour) are returned with every exact answer.
- **No evidence ⇒ no answer**: weak retrieval returns "could not verify from indexed sources" (`verified: false`), not a guess.
- Document text is treated as data: the LLM sees it in delimited evidence blocks, never executes it, and no SQL/code from documents or prompts is run (an LLM may only propose a JSON table plan, which is validated against real columns).
- Ingestion is atomic (staged then renamed); a failure leaves nothing half-indexed.
- Spreadsheet row numbers are real sheet rows (header = row 1).

## Configuration (env, prefix `MKA_`)

See `.env.example`. Keys are read only from the environment (`OPENAI_API_KEY`, `GEMINI_API_KEY`).

- `MKA_LLM_PROVIDER` = `none` | `openai` | `gemini`. With `none`, answers are extracted passages / extractive summaries.
- `MKA_EMBEDDING_PROVIDER` = `hash` | `openai` | `gemini`. **`hash` is an offline lexical fallback, not true semantic search** — use a real embedder for conceptual questions. Changing the embedder marks existing sources `needs_reindex`.
- `MKA_VECTOR_STORE` = `local` (exact cosine, files in the source folder) | `chroma`. Qdrant is not implemented; add a `VectorBackend` in `app/storage.py`.

## Known limits (honest list)

- Scanned PDFs need OCR (`MKA_OCR_ENABLED=true`, requires `pytesseract` + Tesseract); otherwise pages without text are reported as warnings, and an all-image PDF is rejected.
- URL fetching blocks non-public IPs (incl. on every redirect) and caps size/time, but resolves DNS separately from connecting, so a DNS-rebinding attacker is not fully excluded; run behind an egress proxy in production.
- Ingestion is synchronous (fine to ~tens of MB); very large uploads need a background job queue.
- Exact matches that span a page/row boundary are not counted.
- Table heuristics (no LLM) handle common questions; ambiguous ones get a clarifying question instead of a guess. Header is assumed to be the first non-empty row; no multi-table sheets.
- Cross-source comparison without an LLM shows evidence side by side but does not detect conflicts.
- Not tested here against live OpenAI/Gemini (no keys in this environment); the provider code paths are thin HTTP wrappers.
- No auth, SSO, retention policy or UI — all out of scope per BRD §5.2.
