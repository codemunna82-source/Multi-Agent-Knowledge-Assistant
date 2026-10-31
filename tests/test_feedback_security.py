import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.eval.dataset import EvalDataset

from .conftest import make_pdf

PW = "correct horse battery"
PUBLIC = {("GET", "/auth/oidc/config"), ("GET", "/auth/oidc/login"), ("GET", "/auth/oidc/callback"), ("POST", "/auth/signup"), ("POST", "/auth/login"), ("POST", "/auth/refresh"), ("GET", "/health"), ("GET", "/")}


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="10000/minute", rate_limit_auth="10000/minute", rate_limit_ingest="10000/minute", _env_file=None)
    c = TestClient(create_app(s))
    adm = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
    users = {}
    for role in ("user", "manager"):
        c.post("/admin/users", json={"email": f"{role}@acme.io", "password": PW, "role": role}, headers=adm)
        users[role] = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": f"{role}@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
    return c, adm, users


# ----------------------------------------------------------------------------- authorisation matrix (generated from the OpenAPI document)
def _routes(c):
    spec = c.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                yield method.upper(), path


def _fill(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", "0" * 32, path)


def test_every_route_rejects_anonymous_callers_except_the_public_ones(env):
    c, _, _ = env
    checked = 0
    for method, path in _routes(c):
        if (method, path) in PUBLIC or path.startswith(("/docs", "/redoc", "/openapi", "/assets", "/classic")):
            continue
        r = c.request(method, _fill(path), json={} if method in ("POST", "PUT", "PATCH") else None)
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without credentials"
        checked += 1
    assert checked >= 70                                                                   # the whole API surface, not a sample


def test_role_boundaries_user_cannot_manage_and_manager_cannot_administer(env):
    c, adm, u = env
    admin_only = [("GET", "/admin/users"), ("POST", "/admin/users"), ("GET", "/admin/audit"), ("GET", "/admin/audit/export"), ("GET", "/admin/settings"), ("PUT", "/admin/tenant-settings"),
                  ("POST", "/admin/maintenance/run"), ("DELETE", "/admin/data"), ("DELETE", "/session")]
    manager_up = [("POST", "/sources/url"), ("POST", "/learn/demo-corpus"), ("POST", "/eval/run"), ("GET", "/eval/runs"), ("GET", "/feedback/summary"), ("GET", "/feedback/eval-dataset")]
    for m, p in admin_only:
        assert c.request(m, p, headers=u["user"], json={} if m in ("POST", "PUT") else None).status_code == 403, ("user", m, p)
        assert c.request(m, p, headers=u["manager"], json={} if m in ("POST", "PUT") else None).status_code == 403, ("manager", m, p)
    for m, p in manager_up:
        assert c.request(m, p, headers=u["user"], json={} if m == "POST" else None).status_code == 403, ("user", m, p)
        assert c.request(m, p, headers=u["manager"], json={} if m == "POST" else None).status_code != 403, ("manager", m, p)


def test_security_headers_and_no_stack_traces(env):
    c, adm, _ = env
    r = c.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in c.get("/").headers["content-security-policy"]
    for payload in ("../../etc/passwd", "'; DROP TABLE users;--", "<script>alert(1)</script>", "\x00", "A" * 5000):
        r = c.post("/ask", json={"question": payload}, headers=adm)
        assert r.status_code in (200, 422) and "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()
    assert c.get("/sources/..%2F..%2Fetc%2Fpasswd", headers=adm).status_code in (404, 422)
    assert c.get("/sources", headers={**adm, "X-Session-ID": "../x"}).status_code == 400


def test_token_tampering_and_expiry_are_rejected(env):
    c, adm, _ = env
    tok = adm["Authorization"].split()[1]
    head, body, sig = tok.split(".")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {head}.{body}.{sig[:-2]}xx"}).status_code == 401
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {head}.{body}."}).status_code == 401
    import base64
    import json as j

    forged = base64.urlsafe_b64encode(j.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {forged}.{body}."}).status_code == 401      # alg=none is never accepted


# ----------------------------------------------------------------------------- feedback
def test_feedback_roundtrip_summary_and_eval_export(env):
    c, adm, u = env
    c.post("/sources/upload", files=[("files", ("p.pdf", make_pdf(["Employees accrue 25 days of annual leave per year."])))], headers=adm)
    up = c.post("/feedback", json={"rating": 1, "route": "semantic"}, headers=u["user"])
    assert up.status_code == 201 and up.json()["question"] is None                           # a thumbs-up stores no text unless sent
    down = c.post("/feedback", json={"rating": -1, "route": "semantic", "question": "How many leave days?", "answer": "I do not know", "expected": "25 days", "comment": "wrong",
                                     "sources": [{"source": "p.pdf", "location": "page 1"}]}, headers=u["user"])
    assert down.status_code == 201
    assert c.post("/feedback", json={"rating": 0}, headers=u["user"]).status_code == 422
    assert [f["rating"] for f in c.get("/feedback", headers=u["user"]).json()] == [-1, 1]
    assert c.get("/feedback?rating=-1", headers=u["user"]).headers["x-total-count"] == "1"
    assert c.get("/feedback", headers=u["manager"]).json() == []                              # not shared with other users
    assert len(c.get("/feedback", headers=adm).json()) == 2                                   # admin sees the organisation
    assert c.get("/feedback/summary", headers=u["manager"]).json() == {"by_route": {"semantic": {"up": 1, "down": 1}}, "up": 1, "down": 1}
    ds = c.get("/feedback/eval-dataset", headers=u["manager"]).json()
    parsed = EvalDataset(**ds)                                                                # valid input for POST /eval/run
    assert parsed.cases[0].question == "How many leave days?" and parsed.cases[0].expected_keywords == ["25 days"] and parsed.cases[0].relevant[0].source == "p.pdf"
    run = c.post("/eval/run", json={"dataset": ds, "use_llm_judge": False}, headers=u["manager"]).json()
    assert run["metrics"]["cases"] == 1 and run["metrics"]["answers"]["keyword_accuracy"] == 1.0         # the exported case really runs, and the system now answers it
    assert c.delete(f"/feedback/{up.json()['id']}", headers=u["manager"]).status_code == 404
    assert c.delete(f"/feedback/{up.json()['id']}", headers=u["user"]).status_code == 200


def test_feedback_without_checkable_content_is_not_exported_and_masking_applies(env):
    c, adm, u = env
    c.post("/feedback", json={"rating": -1, "question": "Why?", "answer": "x"}, headers=u["user"])
    assert c.get("/feedback/eval-dataset", headers=u["manager"]).status_code == 404
    c.put("/admin/tenant-settings", json={"retention_days_documents": None, "retention_days_conversations": None, "retention_days_audit": None, "retention_days_reports": None,
                                          "web_allowed": True, "web_allowed_domains": [], "redact_stored_messages": True}, headers=adm)
    f = c.post("/feedback", json={"rating": -1, "question": "Mail ann@example.com about leave", "expected": "25 days"}, headers=u["user"]).json()
    assert "ann@example.com" not in f["question"] and "[email]" in f["question"]


# ----------------------------------------------------------------------------- audit export for a SIEM
def test_audit_export_formats_and_safety(env):
    c, adm, u = env
    c.post("/ask", json={"question": "secret question text"}, headers=u["user"])
    nd = c.get("/admin/audit/export?format=ndjson", headers=adm)
    rows = [json.loads(x) for x in nd.text.strip().splitlines()]
    assert nd.headers["content-type"].startswith("application/x-ndjson") and {"ts", "action", "outcome", "user_id"} <= set(rows[0]) and any(r["action"] == "ask" for r in rows)
    assert "secret question text" not in nd.text                                              # the audit trail never holds question text
    csv_ = c.get("/admin/audit/export?format=csv", headers=adm).text
    assert csv_.splitlines()[0].startswith("id,ts,tenant_id") and "ask" in csv_
    cef = c.get("/admin/audit/export?format=cef", headers=adm).text
    assert cef.startswith("CEF:0|MKA|KnowledgeAssistant|3.1|") and "suser=" in cef
    assert c.get("/admin/audit/export?format=xml", headers=adm).status_code == 422
    assert c.get("/admin/audit/export?since=notadate", headers=adm).status_code == 422
    assert c.get("/admin/audit/export", headers=u["manager"]).status_code == 403
    other = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Beta", "email": "b@beta.io", "password": PW}).json()["access_token"]}
    assert "ask" not in [json.loads(x)["action"] for x in c.get("/admin/audit/export", headers=other).text.strip().splitlines()]    # tenant-scoped
