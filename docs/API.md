# API reference

Generated from the running application (`python scripts/gen_api_docs.py`). Interactive docs: `GET /docs` (Swagger UI) and `GET /redoc`;
machine-readable: [`openapi.json`](openapi.json).

**Conventions** — `Authorization: Bearer <JWT>` (when `MKA_AUTH_ENABLED=true`); `X-Session-ID: <workspace>` selects the document workspace inside your tenant (default `default`); `X-Request-ID` is echoed back and stored in the audit log; errors are `{ "detail": ... }` with 401/403/404/409/413/422/429/502 as appropriate; `429` carries `Retry-After`.

## admin

### `GET /admin/audit`

Parameters: `action` (query), `outcome` (query), `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `DELETE /admin/data`

Irreversibly erase every document, vector, conversation, job and evaluation of the caller's tenant (users are kept).

Parameters: `x-session-id` (header)

Body: `application/json` → `PurgeRequest`

Responses: 200, 422 · Access: admin

### `POST /admin/maintenance/run`

Same tasks as the scheduler, restricted to your organisation. Retention periods come from /admin/tenant-settings.

Parameters: `x-session-id` (header)

Body: `application/json` → `MaintenanceBody`

Responses: 200, 422 · Access: admin

### `GET /admin/settings`

Effective configuration; secrets are masked and never returned.

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `GET /admin/tenant-settings`

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `PUT /admin/tenant-settings`

Retention periods, approved web domains and message redaction for the whole organisation.

Parameters: `x-session-id` (header)

Body: `application/json` → `TenantSettingsBody`

Responses: 200, 422 · Access: admin

### `GET /admin/users`

Parameters: `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `POST /admin/users`

Parameters: `x-session-id` (header)

Body: `application/json` → `UserCreate`

Responses: 201, 422 · Access: admin

### `DELETE /admin/users/{user_id}`

Parameters: `user_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `PATCH /admin/users/{user_id}`

Parameters: `user_id` (path, required), `x-session-id` (header)

Body: `application/json` → `UserUpdate`

Responses: 200, 422 · Access: admin

## analytics

### `GET /analytics/anomalies`

Parameters: `source_id` (query, required), `column` (query, required), `sheet` (query), `method` (query), `threshold` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user

### `POST /analytics/ask`

Parameters: `x-session-id` (header)

Body: `application/json` → `AskBody`

Responses: 200, 422 · Access: user

### `POST /analytics/chart`

Parameters: `x-session-id` (header)

Body: `application/json` → `ChartBody`

Responses: 200, 422 · Access: user

### `GET /analytics/profile`

Parameters: `source_id` (query, required), `sheet` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user

### `POST /analytics/sql`

Parameters: `x-session-id` (header)

Body: `application/json` → `SqlBody`

Responses: 200, 422 · Access: user

### `GET /analytics/tables`

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: user

### `GET /analytics/trend`

Parameters: `source_id` (query, required), `date_column` (query, required), `sheet` (query), `value_column` (query), `freq` (query), `agg` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user

## auth

### `POST /auth/login`

Body: `application/json` → `LoginRequest`

Responses: 200, 422 · Access: public (signup/login/refresh) / any user

### `POST /auth/logout`

Revokes the access token and the whole refresh-token family of this login.

Parameters: `mka_refresh` (cookie)

Body: `application/json`

Responses: 200, 422 · Access: public (signup/login/refresh) / any user

### `GET /auth/me`

Responses: 200 · Access: public (signup/login/refresh) / any user

### `POST /auth/refresh`

Exchange a refresh token (body or httpOnly cookie) for a new access token; the refresh token rotates on every use. `optional=true` (used by the browser on page load): a missing or invalid token answers 200 {"authenticated": false} instead of 401, so signed-out visits stay quiet.

Parameters: `optional` (query), `mka_refresh` (cookie)

Body: `application/json`

Responses: 200, 422 · Access: public (signup/login/refresh) / any user

### `POST /auth/signup`

Create a new tenant with its first admin. Disabled in production (use `python -m app.cli create-tenant`).

Body: `application/json` → `SignupRequest`

Responses: 201, 422 · Access: public (signup/login/refresh) / any user

## chat

### `POST /ask`

Parameters: `x-session-id` (header)

Body: `application/json` → `AskRequest`

Responses: 200, 422 · Access: user

### `POST /ask/stream`

Server-Sent Events: `step` (real graph progress), `token` (answer text pieces), `final` (full response incl. citations), `error`.

Parameters: `x-session-id` (header)

Body: `application/json` → `AskRequest`

Responses: 200, 422 · Access: user

### `GET /conversations`

Parameters: `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (own conversations only)

### `POST /conversations`

Parameters: `x-session-id` (header)

Responses: 201, 422 · Access: user (own conversations only)

### `DELETE /conversations/{conv_id}`

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own conversations only)

### `PATCH /conversations/{conv_id}`

Parameters: `conv_id` (path, required), `x-session-id` (header)

Body: `application/json` → `ConversationPatch`

Responses: 200, 422 · Access: user (own conversations only)

### `GET /conversations/{conv_id}/messages`

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own conversations only)

### `GET /conversations/{conv_id}/trace`

Checkpoint trail of the agent graph for this conversation (route, per-node trace, verification) - newest first.

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own conversations only)

### `DELETE /session`

Delete ALL sources of the current workspace (X-Session-ID) and its conversation memory.

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: admin

## evaluation

### `POST /eval/run`

Runs synchronously (a few seconds for the sample; up to 500 questions otherwise). Results are stored per tenant.

Parameters: `x-session-id` (header)

Body: `application/json` → `EvalRequest`

Responses: 200, 422 · Access: manager

### `GET /eval/runs`

Parameters: `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: manager

### `GET /eval/runs/{run_id}`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: manager

### `GET /eval/runs/{run_id}/report.html`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: manager

### `GET /eval/runs/{run_id}/report.md`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: manager

### `GET /eval/runs/{run_id}/report.{fmt}`

Parameters: `run_id` (path, required), `fmt` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: manager

## intelligence

### `GET /graph`

Knowledge graph view: top entities; neighbours of `entity`; or the shortest connection between `entity` and `to`.

Parameters: `entity` (query), `to` (query), `limit` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user

### `GET /sources/{source_id}/entities`

Parameters: `source_id` (path, required), `types` (query), `use_llm` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/questions`

Parameters: `source_id` (path, required), `n` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /transcribe`

Speech-to-text for voice queries (OpenAI Whisper). Browsers can alternatively use client-side speech recognition.

Parameters: `x-session-id` (header)

Body: `multipart/form-data` → `Body_transcribe_transcribe_post`

Responses: 200, 422 · Access: user

## jobs

### `GET /jobs`

Parameters: `limit` (query), `offset` (query), `all_workspaces` (query), `x-session-id` (header)

Responses: 200, 422 · Access: manager

### `GET /jobs/{job_id}`

Parameters: `job_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: manager

## learn

### `POST /learn/demo-corpus`

Parameters: `x-session-id` (header)

Responses: 200, 422

### `GET /learn/graph`

Parameters: `x-session-id` (header)

Responses: 200, 422

### `POST /learn/graph/run`

Parameters: `x-session-id` (header)

Body: `application/json` → `GraphRunBody`

Responses: 200, 422

### `POST /learn/langchain`

Parameters: `x-session-id` (header)

Body: `application/json` → `LcBody`

Responses: 200, 422

### `GET /learn/lessons`

Parameters: `x-session-id` (header)

Responses: 200, 422

### `POST /learn/retrieval/ablation`

Parameters: `x-session-id` (header)

Body: `application/json` → `LabBody`

Responses: 200, 422

### `POST /learn/retrieval/compare`

Parameters: `x-session-id` (header)

Body: `application/json` → `app__api__routers__learn__CompareBody`

Responses: 200, 422

## memory

### `DELETE /memory`

Parameters: `conversations` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (own data)

### `GET /memory/facts`

Parameters: `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (own data)

### `POST /memory/facts`

Save a note you explicitly want remembered. Notes that look like secrets, card/ID numbers, e-mail addresses or phone numbers are refused.

Parameters: `x-session-id` (header)

Body: `application/json` → `FactBody`

Responses: 201, 422 · Access: user (own data)

### `DELETE /memory/facts/{fact_id}`

Parameters: `fact_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own data)

### `GET /memory/preferences`

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: user (own data)

### `PUT /memory/preferences`

Parameters: `x-session-id` (header)

Body: `application/json` → `PrefsBody`

Responses: 200, 422 · Access: user (own data)

## reports

### `GET /reports`

Parameters: `kind` (query), `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (own reports; admin: whole organisation)

### `POST /reports`

Parameters: `x-session-id` (header)

Body: `application/json` → `ReportBody`

Responses: 201, 422 · Access: user (own reports; admin: whole organisation)

### `DELETE /reports/{report_id}`

Parameters: `report_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own reports; admin: whole organisation)

### `GET /reports/{report_id}`

Parameters: `report_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own reports; admin: whole organisation)

### `GET /reports/{report_id}/download`

Parameters: `report_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (own reports; admin: whole organisation)

## search & analysis

### `POST /compare`

Parameters: `x-session-id` (header)

Body: `application/json` → `app__api__routers__features__CompareBody`

Responses: 200, 422 · Access: user

### `POST /search/exact`

Parameters: `limit` (query), `offset` (query), `x-session-id` (header)

Body: `application/json` → `ExactBody`

Responses: 200, 422 · Access: user

### `GET /sources/{source_id}/changes`

Parameters: `source_id` (path, required), `against` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /summaries`

Parameters: `x-session-id` (header)

Body: `application/json` → `SummaryBody`

Responses: 200, 422 · Access: user

### `POST /web/research`

Parameters: `x-session-id` (header)

Body: `application/json` → `WebBody`

Responses: 200, 422 · Access: user

## sources

### `GET /sources`

Documents visible to you (current versions; include_versions=true adds superseded ones). Paginated: limit/offset, total in X-Total-Count.

Parameters: `include_versions` (query), `kind` (query), `q` (query), `limit` (query), `offset` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /sources/upload`

Multi-file upload. Default: synchronous (validated, extracted, embedded and indexed before the response). With ?async=true: files are queued for background workers and 202 + job ids are returned. An identical file already indexed in the workspace is reported as `duplicate` (unless allow_duplicate); a file with the same name but different content becomes a new VERSION of that document (older versions stay available for comparison but are not searched).

Parameters: `async` (query), `x-session-id` (header)

Body: `multipart/form-data` → `Body_upload_sources_upload_post`

Responses: 200, 202, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /sources/url`

Parameters: `visibility` (query), `async` (query), `x-session-id` (header)

Body: `application/json` → `UrlRequest`

Responses: 200, 202, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `DELETE /sources/{source_id}`

Deletes text, chunks, vectors and the original file. Deleting the current version restores the newest older one; all_versions=true removes the document entirely.

Parameters: `source_id` (path, required), `all_versions` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/classification`

Document type from a closed taxonomy (contract, invoice, policy, report, ...) with confidence and method (keywords | structure | llm).

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /sources/{source_id}/make-current`

Roll back / forward: make this version the searchable one.

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/pages/{page}/image`

PNG of a PDF page with the cited text highlighted (PDF sources only; needs PyMuPDF).

Parameters: `source_id` (path, required), `page` (path, required), `highlight` (query), `zoom` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/passage`

The extracted text at a citation location (+ the neighbouring passages) - used by the dashboard to preview a cited passage.

Parameters: `source_id` (path, required), `page` (query), `row` (query), `sheet` (query), `paragraph` (query), `line` (query), `table` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `POST /sources/{source_id}/reindex`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/sharing`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `PUT /sources/{source_id}/sharing`

Document-level permissions: 'tenant' (everyone in the organisation), 'private' (owner + admins) or 'restricted' (owner + the listed users/roles + admins).

Parameters: `source_id` (path, required), `x-session-id` (header)

Body: `application/json` → `SharingBody`

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/tables`

Structured tables extracted from the source (spreadsheets, DOCX, HTML, PDF), each with its location.

Parameters: `source_id` (path, required), `max_rows` (query), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/timeline`

Chronological list of dated events (the sentence around every date) with citations.

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

### `GET /sources/{source_id}/versions`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)

## system

### `GET /health`

Responses: 200 · Access: public

