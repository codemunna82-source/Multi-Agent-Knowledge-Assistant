"""Small, honest load test against a REAL server process (uvicorn, auth on, rate limits raised):  python scripts/loadtest.py [--users 16] [--requests 30]
Creates a tenant, uploads a few documents, then N concurrent users each fire M mixed requests (ask / exact search / spreadsheet question / health).
Reports throughput, latency percentiles and error rate. It measures THIS machine with the offline configuration - not a capacity plan."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

PW = "correct horse battery"
MIX = [("POST", "/ask", {"question": "How many days of annual leave do full-time employees accrue?"}), ("POST", "/ask", {"question": "Within how many hours must a security incident be reported?"}),
       ("POST", "/search/exact", {"term": "Anjali Rao"}), ("POST", "/ask", {"question": "Which employee has the highest sales?"}), ("GET", "/health", None), ("POST", "/ask", {"question": "What is the capital of Mongolia?"})]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=16)
    ap.add_argument("--requests", type=int, default=30)
    ap.add_argument("--port", default="8793")
    ap.add_argument("--out", default=str(root / "docs" / "loadtest.json"))
    a = ap.parse_args()
    data = tempfile.mkdtemp(prefix="mka-load-")
    env = {**os.environ, "MKA_DATA_DIR": data, "MKA_AUTH_ENABLED": "true", "MKA_JWT_SECRET": "load-" + "x" * 40, "MKA_RATE_LIMIT_ASK": "100000/minute", "MKA_RATE_LIMIT_INGEST": "100000/minute", "MKA_RATE_LIMIT_AUTH": "100000/minute"}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", a.port, "--log-level", "warning"], cwd=root, env=env)
    base = f"http://127.0.0.1:{a.port}"
    try:
        for _ in range(80):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        tok = httpx.post(base + "/auth/signup", json={"tenant_name": "Load", "email": "l@load.io", "password": PW}, timeout=10).json()["access_token"]
        H = {"Authorization": "Bearer " + tok, "X-Session-ID": "load"}
        from app.eval.sample import corpus

        files = [("files", (n, d)) for n, d in corpus().items()]
        r = httpx.post(base + "/sources/upload", files=files, headers=H, timeout=120)
        assert r.status_code == 200 and all(x["status"] == "ready" for x in r.json()), r.text[:300]
        lat: list[float] = []
        errors: list[str] = []
        lock = threading.Lock()

        def user(i: int):
            with httpx.Client(base_url=base, headers=H, timeout=60) as c:
                for j in range(a.requests):
                    m, p, b = MIX[(i + j) % len(MIX)]
                    t0 = time.perf_counter()
                    try:
                        resp = c.request(m, p, json=b)
                        ok = resp.status_code == 200
                    except Exception as e:  # noqa: BLE001
                        ok, resp = False, type("R", (), {"status_code": type(e).__name__})
                    dt = (time.perf_counter() - t0) * 1000
                    with lock:
                        lat.append(dt)
                        if not ok:
                            errors.append(f"{m} {p} -> {resp.status_code}")

        t0 = time.perf_counter()
        ts = [threading.Thread(target=user, args=(i,)) for i in range(a.users)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        wall = time.perf_counter() - t0
        lat.sort()
        q = lambda p: round(lat[min(len(lat) - 1, int(p / 100 * len(lat)))], 1)  # noqa: E731
        res = {"users": a.users, "requests_per_user": a.requests, "total": len(lat), "wall_s": round(wall, 1), "throughput_rps": round(len(lat) / wall, 1), "p50_ms": q(50), "p95_ms": q(95), "p99_ms": q(99),
               "max_ms": round(lat[-1], 1), "mean_ms": round(statistics.mean(lat), 1), "errors": len(errors), "error_sample": errors[:5], "config": "offline (hash embedder, no LLM), SQLite, in-process queue, 1 uvicorn worker, 4 vCPU sandbox"}
        Path(a.out).write_text(json.dumps(res, indent=1))
        print(json.dumps(res, indent=1))
        return 1 if errors else 0
    finally:
        srv.terminate()


if __name__ == "__main__":
    sys.exit(main())
