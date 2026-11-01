# Operations guide

> The compose file and Dockerfile are validated with `docker compose config` / a `docker build` job in CI, but **no container runtime was available in the build environment**, so image build and stack start-up have not been executed by the authors. The same process model (API, worker, scheduler, PostgreSQL, Redis) *was* executed as plain processes by `scripts/prod_smoke.py`.

## 1. Deployment

```bash
cp .env.example .env                                  # MKA_JWT_SECRET (>= 32 chars), provider keys (optional)
export POSTGRES_PASSWORD=$(openssl rand -hex 16)
docker compose up --build -d                          # api · worker · scheduler · postgres · redis · qdrant
docker compose exec api python -m app.cli create-tenant --name "ACME" --email admin@acme.com
curl -fsS localhost:8000/health
```

* `MKA_ENV=production` refuses to start with auth off, a weak JWT secret, open signup, private-URL fetching, wildcard CORS or SQLite.
* Schema migrations run automatically at API start in production (`MKA_AUTO_MIGRATE=true` in the compose file) under a PostgreSQL advisory lock, so several replicas can start together. Manual control: `python -m app.cli migrate`, `alembic current`, `alembic check`.
* Scale: the API is stateless (add replicas behind a proxy with `--proxy-headers`); add `worker` replicas for ingestion throughput; run one or more `scheduler` replicas (a Redis lock elects a leader per round).
* The API, worker and scheduler **share the data volume** (`MKA_DATA_DIR`). Use a network filesystem or object-storage gateway for multi-host deployments (native object storage is not implemented).
* Secrets: `MKA_JWT_SECRET_FILE`, `OPENAI_API_KEY_FILE`, `MKA_DATABASE_URL_FILE`, … read secrets from mounted files (Docker/Kubernetes secrets).

## 2. Monitoring

| Signal | Where |
|---|---|
| Liveness / config summary | `GET /health` |
| Prometheus metrics | `GET /metrics` (auth on ⇒ `Authorization: Bearer $MKA_METRICS_TOKEN` or an admin JWT). Series: `mka_http_requests_total`, `mka_http_request_seconds`, `mka_questions_total{route,verified}`, `mka_agent_node_runs_total{node,outcome}`, `mka_agent_node_seconds`, `mka_tool_calls_total{tool,outcome}` (`ok` / `declined` / `error`), `mka_llm_tokens_total`, `mka_llm_cost_usd_total`, `mka_citations_total{status}`, `mka_ingest_total`, `mka_ingest_seconds`, `mka_maintenance_runs_total` |
| Traces | set `MKA_OTEL_ENDPOINT=http://collector:4317`; spans `agent.<node>`, `tool.<name>` (OTLP/gRPC) |
| LangSmith | set `MKA_LANGSMITH_API_KEY` (exports the `LANGSMITH_*` variables). *Not verified against the live service.* |
| Logs | JSON lines on stdout with `request_id`, path, status, ms |
| Audit | `GET /admin/audit` (hashes and metadata only, never question or document text) |

Suggested alerts: `rate(mka_agent_node_runs_total{outcome=~"error|timeout"}[5m]) > 0`, `rate(mka_tool_calls_total{outcome="error"}[5m]) > 0`, `histogram_quantile(0.95, rate(mka_http_request_seconds_bucket[5m])) > 10`, `rate(mka_citations_total{status="invalid"}[1h]) > 0`.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: mka
    metrics_path: /metrics
    authorization: { credentials: "<MKA_METRICS_TOKEN>" }
    static_configs: [{ targets: ["api:8000"] }]
```

## 3. Data retention and deletion

* Per-tenant periods (Settings → Organisation policy, `PUT /admin/tenant-settings`): documents, conversations, audit (minimum 30 days), reports. Empty = keep.
* The scheduler (`python -m app.scheduler`, hourly by default) applies them; `POST /admin/maintenance/run {"dry_run": true}` previews what would be removed for your organisation. Every sweep writes a `retention_sweep` audit event.
* Right-to-erasure: `DELETE /sources/{id}?all_versions=true`, `DELETE /memory?conversations=true` (own data), `DELETE /admin/users/{id}` (conversations, notes, reports, refresh tokens), `DELETE /admin/data` (whole tenant).
* Redaction: with `redact_stored_messages` on, e-mail addresses, phone numbers, card numbers (Luhn-checked), national-ID-like numbers and secrets are masked in stored messages. Pattern-based; not a guarantee.

## 4. Backup and recovery

What to back up (all three are needed for a consistent restore):

| Component | Contains | Backup | Restore |
|---|---|---|---|
| PostgreSQL | users, tenants, document registry + ACL, conversations, jobs, audit, reports index, LangGraph checkpoints | `pg_dump -Fc -f mka.dump "$MKA_DATABASE_URL"` (nightly) + WAL archiving for point-in-time recovery | `pg_restore --clean --if-exists -d mka mka.dump`, then `python -m app.cli migrate` |
| Data volume (`/data`) | original files, extracted units, chunks, tables, graphs, generated reports, local vectors | `tar -C /data -czf data.tgz .` or volume snapshots, taken **right after** the database dump | extract to an empty volume |
| Qdrant (when used) | vectors | `POST /collections/<name>/snapshots` per collection or storage-volume snapshot | restore snapshot **or** rebuild: `POST /sources/{id}/reindex` for each source (vectors are derived data) |

`scripts/backup.sh` and `scripts/restore.sh` wrap the PostgreSQL + volume steps.

Recovery notes: vectors are derived from the stored chunks, so losing Qdrant is recoverable by re-indexing (slow, but lossless); losing the *data volume* loses the documents (restore from backup; registry rows whose files are missing fail on preview/re-index with a clear error); losing PostgreSQL loses identities and history. Test a restore at least once per quarter: start an empty stack, restore, run `python scripts/prod_smoke.py`-style checks (login, list sources, ask).

RPO/RTO are set by your backup cadence; there is no built-in replication.

## 5. Upgrades and rollbacks

1. Back up (section 4). 2. Deploy the new image; the first API start migrates the schema. 3. `curl /health`, run a smoke question. Rollback: restore the PostgreSQL dump taken in step 1 and start the previous image (migrations are forward-only except `downgrade()` in `migrations/versions/0002`, which maps `user`/`manager` back to `viewer`/`editor`).

Changing the embedding model flags every source *needs re-index*; re-index from the UI/API (`POST /sources/{id}/reindex`).

## 5a. Single sign-on, two-step sign-in, streaming, Kubernetes

* **OIDC SSO** – set `MKA_OIDC_ISSUER`, `MKA_OIDC_CLIENT_ID`, `MKA_OIDC_REDIRECT_URI` (and a client secret if the IdP requires one); the login page then shows "Sign in with single sign-on". Users are matched by (issuer, subject); an existing local account is linked only when the IdP reports `email_verified`. Unknown users are refused unless `MKA_OIDC_AUTO_PROVISION=true` with `MKA_OIDC_TENANT_ID` (role `user`/`manager` only – SSO never creates admins). Use `MKA_OIDC_ALLOWED_DOMAINS` to restrict e-mail domains. SSO logins rely on the IdP for MFA (the local authenticator code is not asked again). Tested against a mock IdP only – verify with your real provider in staging.
* **Two-step sign-in (TOTP)** – users enrol in *Settings → Two-step sign-in*; ten single-use recovery codes are shown once. A lost device: sign in with a recovery code, then turn MFA off and on again. An administrator who is locked out completely can clear the row: `DELETE FROM user_mfa WHERE user_id = '<id>'`. The TOTP secret is stored unencrypted in the database (protect the database and its backups accordingly).
* **Streaming (`POST /ask/stream`, Server-Sent Events)** – same authentication, validation and rate limit as `/ask`. Events: `status` (a pipeline stage started: understand / retrieve / grade / rerank / generate / verify …, short operational labels only), `step` (a graph node finished), `draft` (real provider tokens, **unverified**), `draft_reset` (a regenerated draft replaces the previous one), `final` (verified answer + citations), `done`, `error`; `: ping` comment lines keep idle connections alive. With no LLM configured there are no `draft` events: the extractive answer arrives whole in `final` (nothing is simulated). **Stop** = the browser closes the connection; the server cancels the provider stream mid-generation, stores nothing and leaves no empty conversation. A stream longer than `MKA_STREAM_TIMEOUT_S` (default 300) ends with an `error` event. `regenerate: true` in the request replaces the conversation's latest exchange – the old one is deleted only after the new answer succeeded. Behind a reverse proxy disable response buffering for this path (nginx: `proxy_buffering off`, already set by the chart's ingress annotation).
* **Encrypting TOTP seeds** – set `MKA_DATA_KEY` (Fernet key, see `.env.example`) *before* users enrol; seeds enrolled earlier stay readable and are encrypted when the user re-enrols. Back the key up separately from the database: without it encrypted seeds are unreadable and those users must re-enrol (clear their row, see above).
* **Notifications** – alerts and scheduled reports accept an https webhook (Slack incoming-webhook URLs are recognised and get a readable message) or `mailto:person@example.com` (needs `MKA_SMTP_HOST`). Messages carry document names, counts and locations, never document text.
* **SIEM** – set `MKA_SIEM_URL` (+ `MKA_SIEM_TOKEN`, `MKA_SIEM_FORMAT`); the scheduler's `ship_audit` task posts new audit events in batches and advances a cursor (`<data dir>/siem_cursor.json`) only after the collector answers 2xx, so a collector outage delays but never loses events (a crash between delivery and cursor write can re-send a batch).
* **Chunking** – `MKA_CHUNK_STRATEGY=structure` keeps clauses/sections together; it applies to documents indexed afterwards (re-index existing ones).
* **Kubernetes** – `deploy/helm/mka` (API, worker, scheduler; PostgreSQL, Redis and Qdrant must exist; secrets come from one existing Secret). It has not been rendered or installed by the authors – run `helm lint` / `helm template` and review first.

## 6. Limits and tuning (measured in `docs/PERFORMANCE.md`)

`MKA_MAX_UPLOAD_MB` (50), `MKA_MAX_PDF_PAGES` (5000), `MKA_NODE_TIMEOUT_S` (120), `MKA_JOB_WORKERS`, `MKA_MAX_VERSIONS_PER_DOCUMENT` (5), report size cap (`MKA_REPORT_MAX_MB`), SQL sandbox (3 s, 200 rows per preview call, 2000 max). PyMuPDF is AGPL-3.0/commercial – decide on licensing before distributing; `MKA_PDF_ENGINE=pypdf` avoids it (slower, no page images).

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| API exits at start in production | the message lists every insecure setting |
| Ingestion stuck at *queued* | worker running? `MKA_JOB_BACKEND=redis` needs `python -m app.worker` and a shared `MKA_DATA_DIR` |
| 401 after reload | refresh cookie is `Secure` in production: serve over HTTPS; cookie path `/auth` |
| Hindi text garbled in a PDF report | reportlab does not shape Devanagari: export DOCX/XLSX or set `MKA_REPORT_FONT` (shaping still not applied) |
| `answers say "needs re-index"` | embedding model changed since ingestion |
| `agent step timed out` | raise `MKA_NODE_TIMEOUT_S`, check provider latency (`mka_agent_node_seconds`) |

## AI Learning Academy

* **Code runner** (`POST /academy/code/run`) never executes learner code in the API process. On Linux it starts a child under `unshare --user --map-root-user --net --mount --pid`, `prlimit` limits (CPU, memory, file size, open files) and a `chroot` into a minimal read-only root with a 32 MB tmpfs `/tmp`; there is no network and no access to the server's files or environment. `GET /academy/code/status` says whether it is available. **If the host forbids unprivileged user namespaces (the default Docker seccomp profile does), the runner reports "unavailable" and executes nothing** – run the container with a profile that allows `unshare`/`clone` of user namespaces, or leave the feature off. There are no cgroups or seccomp filters in this sandbox; for hostile multi-tenant use put it behind gVisor/Firecracker.
* Settings: `MKA_SANDBOX` (`auto`/`off`), `MKA_SANDBOX_TIMEOUT_S`, `MKA_SANDBOX_MEMORY_MB`, `MKA_SANDBOX_CONCURRENCY` (a full queue returns 429), `MKA_RATE_LIMIT_CODE`, `MKA_RATE_LIMIT_PLAYGROUND`.
* **Playgrounds** call the configured LLM/embedder. Without an LLM they say so and show the exact request instead of inventing an answer.
* Progress, quiz attempts, bookmarks and project steps live in the `academy_*` tables (migration 0005) and are removed with the user (`DELETE /admin/users/{id}`).
