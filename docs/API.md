# API reference

Generated from the running application (`python scripts/gen_api_docs.py`). Interactive docs: `GET /docs` (Swagger UI) and `GET /redoc`;
machine-readable: [`openapi.json`](openapi.json).

**Conventions** — `Authorization: Bearer <JWT>` (when `MKA_AUTH_ENABLED=true`); `X-Session-ID: <workspace>` selects the document workspace inside your tenant (default `default`); `X-Request-ID` is echoed back and stored in the audit log; errors are `{ "detail": ... }` with 401/403/404/409/413/422/429/502 as appropriate; `429` carries `Retry-After`.

## admin

### `GET /admin/audit`

Parameters: `action` (query), `limit` (query), `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `DELETE /admin/data`

Irreversibly erase every document, vector, conversation, job and evaluation of the caller's tenant (users are kept).

Parameters: `x-session-id` (header)

Body: `application/json` → `PurgeRequest`

Responses: 200, 422 · Access: admin

### `GET /admin/settings`

Effective configuration; secrets are masked and never returned.

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: admin

### `GET /admin/users`

Parameters: `x-session-id` (header)

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

## auth

### `POST /auth/login`

Body: `application/json` → `LoginRequest`

Responses: 200, 422 · Access: public (signup/login) / any user

### `POST /auth/logout`

Responses: 200 · Access: public (signup/login) / any user

### `GET /auth/me`

Responses: 200 · Access: public (signup/login) / any user

### `POST /auth/signup`

Create a new tenant with its first admin. Disabled in production (use `python -m app.cli create-tenant`).

Body: `application/json` → `SignupRequest`

Responses: 201, 422 · Access: public (signup/login) / any user

## chat

### `POST /ask`

Parameters: `x-session-id` (header)

Body: `application/json` → `AskRequest`

Responses: 200, 422 · Access: viewer

### `POST /ask/stream`

Server-Sent Events: `step` (real graph progress), `token` (answer text pieces), `final` (full response incl. citations), `error`.

Parameters: `x-session-id` (header)

Body: `application/json` → `AskRequest`

Responses: 200, 422 · Access: viewer

### `GET /conversations`

Parameters: `limit` (query), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (own conversations only)

### `POST /conversations`

Parameters: `x-session-id` (header)

Responses: 201, 422 · Access: viewer (own conversations only)

### `DELETE /conversations/{conv_id}`

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (own conversations only)

### `GET /conversations/{conv_id}/messages`

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (own conversations only)

### `GET /conversations/{conv_id}/trace`

Checkpoint trail of the agent graph for this conversation (route, per-node trace, verification) - newest first.

Parameters: `conv_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (own conversations only)

### `DELETE /session`

Delete ALL sources of the current workspace (X-Session-ID) and its conversation memory.

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: admin

## evaluation

### `POST /eval/run`

Runs synchronously (a few seconds for the sample; up to 500 questions otherwise). Results are stored per tenant.

Parameters: `x-session-id` (header)

Body: `application/json` → `EvalRequest`

Responses: 200, 422 · Access: editor

### `GET /eval/runs`

Parameters: `limit` (query), `x-session-id` (header)

Responses: 200, 422 · Access: editor

### `GET /eval/runs/{run_id}`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: editor

### `GET /eval/runs/{run_id}/report.html`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: editor

### `GET /eval/runs/{run_id}/report.md`

Parameters: `run_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: editor

## intelligence

### `GET /graph`

Knowledge graph view: top entities; neighbours of `entity`; or the shortest connection between `entity` and `to`.

Parameters: `entity` (query), `to` (query), `limit` (query), `x-session-id` (header)

Responses: 200, 422 · Access: viewer

### `GET /sources/{source_id}/entities`

Parameters: `source_id` (path, required), `types` (query), `use_llm` (query), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `GET /sources/{source_id}/questions`

Parameters: `source_id` (path, required), `n` (query), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `POST /transcribe`

Speech-to-text for voice queries (OpenAI Whisper). Browsers can alternatively use client-side speech recognition.

Parameters: `x-session-id` (header)

Body: `multipart/form-data` → `Body_transcribe_transcribe_post`

Responses: 200, 422 · Access: viewer

## jobs

### `GET /jobs`

Parameters: `limit` (query), `all_workspaces` (query), `x-session-id` (header)

Responses: 200, 422 · Access: editor

### `GET /jobs/{job_id}`

Parameters: `job_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: editor

## sources

### `GET /sources`

Parameters: `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `POST /sources/upload`

Multi-file upload. Default: synchronous (validated, extracted, embedded and indexed before the response). With ?async=true: files are queued for background workers and 202 + job ids are returned.

Parameters: `async` (query), `x-session-id` (header)

Body: `multipart/form-data` → `Body_upload_sources_upload_post`

Responses: 200, 202, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `POST /sources/url`

Parameters: `visibility` (query), `async` (query), `x-session-id` (header)

Body: `application/json` → `UrlRequest`

Responses: 200, 202, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `DELETE /sources/{source_id}`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `GET /sources/{source_id}`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `POST /sources/{source_id}/reindex`

Parameters: `source_id` (path, required), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

### `GET /sources/{source_id}/tables`

Structured tables extracted from the source (spreadsheets, DOCX, HTML, PDF), each with its location.

Parameters: `source_id` (path, required), `max_rows` (query), `x-session-id` (header)

Responses: 200, 422 · Access: viewer (read) · editor (upload, URL, re-index, delete own) · admin (delete any)

## system

### `GET /health`

Responses: 200 · Access: public

