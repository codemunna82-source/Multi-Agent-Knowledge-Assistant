"""Production-shaped smoke test with REAL processes: API (uvicorn) + separate ingestion worker (python -m app.worker),
PostgreSQL (database + LangGraph checkpoints), Redis (queue + rate limits), tenant created through the CLI, MKA_ENV=production.
Needs a reachable PostgreSQL and Redis:  MKA_SMOKE_PG_URL=postgresql+psycopg2://... MKA_SMOKE_REDIS_URL=redis://...  python scripts/prod_smoke.py"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PG, REDIS = os.environ["MKA_SMOKE_PG_URL"], os.environ["MKA_SMOKE_REDIS_URL"]
PORT = os.environ.get("PORT", "8790")
root = Path(__file__).resolve().parents[1]
data = tempfile.mkdtemp(prefix="mka-prod-")
env = {**os.environ, "MKA_ENV": "production", "MKA_AUTH_ENABLED": "true", "MKA_ALLOW_SIGNUP": "false", "MKA_JWT_SECRET": "prod-smoke-" + "x" * 40,
       "MKA_DATABASE_URL": PG, "MKA_REDIS_URL": REDIS, "MKA_JOB_BACKEND": "redis", "MKA_CHECKPOINT_BACKEND": "postgres", "MKA_DATA_DIR": data,
       "MKA_RATE_LIMIT_ASK": "1000/minute", "MKA_RATE_LIMIT_INGEST": "1000/minute", "MKA_RATE_LIMIT_AUTH": "1000/minute"}
procs: list[subprocess.Popen] = []
ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  [{extra}]" if extra and not cond else ""))


try:
    # fresh schema
    from sqlalchemy import create_engine, text

    eng = create_engine(PG)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    import redis

    redis.Redis.from_url(REDIS).flushdb()

    r = subprocess.run([sys.executable, "-m", "app.cli", "create-tenant", "--name", "Prod Co", "--email", "admin@prod.io", "--password", "a long enough password"], cwd=root, env=env, capture_output=True, text=True)
    check("CLI creates the first tenant/admin", r.returncode == 0 and "tenant created" in r.stdout, r.stderr[-200:])

    bad = subprocess.run([sys.executable, "-c", "from app.api import create_app; create_app()"], cwd=root, env={**env, "MKA_ALLOW_SIGNUP": "true"}, capture_output=True, text=True)
    check("production refuses insecure config (signup enabled)", bad.returncode != 0 and "MKA_ALLOW_SIGNUP" in bad.stderr)

    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", PORT, "--log-level", "warning"], cwd=root, env=env))
    procs.append(subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=root, env=env, stdout=subprocess.DEVNULL))
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(80):
        try:
            if httpx.get(base + "/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    h = httpx.get(base + "/health").json()
    check("API healthy in production mode", h["status"] == "ok" and h["auth_enabled"] is True)
    check("signup endpoint is closed", httpx.post(base + "/auth/signup", json={"tenant_name": "X Co", "email": "x@x.io", "password": "long enough pw"}).status_code == 403)
    check("anonymous access is rejected", httpx.get(base + "/sources").status_code == 401)
    tok = httpx.post(base + "/auth/login", json={"email": "admin@prod.io", "password": "a long enough password"}).json()["access_token"]
    A = {"Authorization": f"Bearer {tok}", "X-Session-ID": "main"}

    up = httpx.post(base + "/sources/upload?async=true", headers=A, files=[("files", ("policy.txt", b"Employees accrue 25 days of annual leave per year.\n\nAnjali Rao is the HR Director."))])
    jid = up.json()[0]["job_id"]
    check("upload accepted and queued (202)", up.status_code == 202 and jid)
    status = ""
    for _ in range(80):
        status = httpx.get(f"{base}/jobs/{jid}", headers=A).json()["status"]
        if status in ("ready", "failed"):
            break
        time.sleep(0.25)
    check("separate worker process ingested the file via Redis", status == "ready", status)
    a = httpx.post(base + "/ask", headers=A, json={"question": "How many days of annual leave do employees accrue?"}).json()
    check("grounded, cited answer", a["verified"] and "25 days" in a["answer"] and a["citations"][0]["source"] == "policy.txt")
    e = httpx.post(base + "/ask", headers=A, json={"question": "Does Anjali Rao appear?", "conversation_id": a["conversation_id"]}).json()
    check("exact search count", e["details"]["count"] == 1)
    tr = httpx.get(f"{base}/conversations/{a['conversation_id']}/trace", headers=A).json()
    check("PostgreSQL checkpoints recorded the agent graph runs", len(tr) >= 2 and tr[0]["route"] == "exact", str(tr)[:200])
    audit = httpx.get(base + "/admin/audit", headers=A).json()
    check("audit trail has login, ingest_job and ask", {"login", "ingest_job", "ask"} <= {x["action"] for x in audit})
    with eng.connect() as c:
        n = c.execute(text("select count(*) from checkpoints")).scalar()
    check("checkpoints table populated in PostgreSQL", n and n > 0)
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
print("\nPRODUCTION SMOKE", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)
