import os
import threading
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.core import ProviderError
from app.jobs import JobService
from app.service import Knowledge

from .conftest import ask, make_pdf
from .fakes import FakeLLM

H = {"X-Session-ID": "w"}


def wait_job(c, jid, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/jobs/{jid}", headers=H).json()
        if j["status"] in ("ready", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_async_upload_progress_and_result(client):
    files = [("files", ("a.pdf", make_pdf(["Quarterly revenue grew 12 percent"]))), ("files", ("b.txt", b"hello world")), ("files", ("c.txt", b""))]
    r = client.post("/sources/upload?async=true", files=files, headers=H)
    assert r.status_code == 202
    items = r.json()
    assert [i["status"] for i in items] == ["queued", "queued", "failed"] and "empty" in items[2]["error"]
    jobs = [wait_job(client, i["job_id"]) for i in items[:2]]
    assert all(j["status"] == "ready" and j["progress"] == 100 and j["source_id"] for j in jobs)
    assert len(client.get("/sources", headers=H).json()) == 2
    assert ask(client, "revenue grew", session="w")["citations"][0]["source"] == "a.pdf"
    assert not [p for p in (Path(client.app.state.svc.settings.data_dir) / "_uploads").rglob("*") if p.is_file()]  # staged uploads cleaned up


def test_async_failure_is_reported_not_retried(client):
    jid = client.post("/sources/upload?async=true", files=[("files", ("bad.pdf", b"not a pdf"))], headers=H).json()[0]["job_id"]
    j = wait_job(client, jid)
    assert j["status"] == "failed" and "not a PDF" in j["error"] and j["attempts"] == 1


def test_transient_failure_retried_boundedly(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), job_retry_backoff=0.01, job_max_attempts=3, _env_file=None)
    k = Knowledge(s)
    real = k.embedder.embed_documents
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("HTTP 503")
        return real(texts)

    k.embedder.embed_documents = flaky
    c = TestClient(create_app(s, k))
    j = wait_job(c, c.post("/sources/upload?async=true", files=[("files", ("a.txt", b"retry me please"))], headers=H).json()[0]["job_id"])
    assert j["status"] == "ready" and j["attempts"] == 3

    calls["n"] = -100  # never succeeds
    j = wait_job(c, c.post("/sources/upload?async=true", files=[("files", ("b.txt", b"hopeless"))], headers=H).json()[0]["job_id"])
    assert j["status"] == "failed" and j["attempts"] == 3 and "503" in j["error"]


def test_async_url_job_and_job_isolation(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="j" * 40, rate_limit_ingest="1000/minute", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    tok = lambda email, t: {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": t, "email": email, "password": "long enough pw"}).json()["access_token"]}
    a, b = tok("a@a.io", "Tenant A"), tok("b@b.io", "Tenant B")
    jid = c.post("/sources/url?async=true", json={"url": "http://127.0.0.1/x"}, headers={**a, **H}).json()[0]["job_id"]
    t0 = time.time()
    while c.get(f"/jobs/{jid}", headers={**a, **H}).json()["status"] in ("queued", "running") and time.time() - t0 < 15:
        time.sleep(0.05)
    j = c.get(f"/jobs/{jid}", headers={**a, **H}).json()
    assert j["status"] == "failed" and "blocked" in j["error"]  # SSRF guard applies to background jobs too
    assert c.get(f"/jobs/{jid}", headers={**b, **H}).status_code == 404
    assert c.get("/jobs", headers={**b, **H}).json() == []


@pytest.mark.skipif(not os.environ.get("MKA_TEST_REDIS_URL"), reason="set MKA_TEST_REDIS_URL")
def test_redis_queue_with_separate_worker(tmp_path):
    import redis

    url = os.environ["MKA_TEST_REDIS_URL"]
    redis.Redis.from_url(url).flushdb()
    s = Settings(data_dir=str(tmp_path / "d"), redis_url=url, job_backend="redis", _env_file=None)
    api = TestClient(create_app(s))  # API process: only enqueues
    assert api.app.state.svc.jobs._pool is None
    jid = api.post("/sources/upload?async=true", files=[("files", ("a.txt", b"processed by a separate worker"))], headers=H).json()[0]["job_id"]
    assert api.get(f"/jobs/{jid}", headers=H).json()["status"] == "queued"
    # worker process (own Knowledge/JobService instance, same DB + data dir)
    worker = JobService(s, api.app.state.svc.db, Knowledge(s), api.app.state.svc.auditor, api.app.state.svc.jobs.redis)
    stop = threading.Event()
    t = threading.Thread(target=worker.work_forever, args=(stop, 1), daemon=True)
    t.start()
    j = wait_job(api, jid)
    stop.set(); t.join(timeout=5)
    assert j["status"] == "ready"
    assert ask(api, 'find "separate worker"', session="w")["details"]["count"] == 1
    assert redis.Redis.from_url(url).llen("mka:jobs:processing") == 0


def test_duplicate_delivery_is_idempotent(client):
    jid = client.post("/sources/upload?async=true", files=[("files", ("a.txt", b"only once"))], headers=H).json()[0]["job_id"]
    wait_job(client, jid)
    client.app.state.svc.jobs.run(jid)  # redelivered
    assert len(client.get("/sources", headers=H).json()) == 1


# ---------------------------------------------------------------------------- vector backends: same behaviour contract
@pytest.mark.parametrize("backend", ["local", "qdrant", "chroma"])
def test_vector_backends_contract(tmp_path, backend):
    s = Settings(data_dir=str(tmp_path / "d"), vector_store=backend, _env_file=None)
    c = TestClient(create_app(s, Knowledge(s)))
    from .conftest import upload

    a = upload(c, "a.txt", b"The warranty period for widgets is 24 months.", session="w")["source"]["id"]
    upload(c, "b.txt", b"Bananas are yellow and grow in tropical climates.", session="w")
    r = ask(c, "How long is the widget warranty?", session="w")
    assert r["verified"] and r["citations"][0]["source"] == "a.txt"
    assert ask(c, "How long is the widget warranty?", session="other")["verified"] is False  # workspace isolation
    c.delete(f"/sources/{a}", headers=H)
    assert not any(x["source"] == "a.txt" for x in ask(c, "How long is the widget warranty?", session="w")["citations"])


def test_qdrant_tenant_filter_is_mandatory(tmp_path):
    from app.storage import QdrantVectors, Scope, SessionStore
    import numpy as np

    s = Settings(data_dir=str(tmp_path / "d"), vector_store="qdrant", _env_file=None)
    q = QdrantVectors(s)
    st_a, st_b = SessionStore(s.data_dir, Scope("ta", "w")), SessionStore(s.data_dir, Scope("tb", "w"))
    v = np.eye(4, dtype=np.float32)
    q.add(st_a, None, "a" * 32, [f"{'a'*32}:{i}" for i in range(4)], v, [""] * 4)
    # tenant B has same workspace + same source id guess: must never see tenant A's points
    meta = {"id": "a" * 32, "embedding": "e"}
    st_b.list_sources = lambda principal=None: [meta]
    st_a.list_sources = lambda principal=None: [meta]
    assert q.search(st_b, v[0], 5, None, "e") == []
    assert q.search(st_a, v[0], 5, None, "e")[0][0] == f"{'a'*32}:0"
    q.delete(st_b, "a" * 32)  # B deleting by id must not touch A
    assert len(q.search(st_a, v[0], 5, None, "e")) == 4
