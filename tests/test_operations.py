import os
import socket
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select

from app import maintenance
from app.agents.routing import split_intents
from app.api import create_app
from app.config import Settings
from app.core import ProviderError
from app.db import AuditEvent, Conversation, Document, Job
from app.ingestion import web
from app.observability import Observability, setup_langsmith
from app.service import Knowledge

from .conftest import SALES_ROWS, ask, make_pdf, make_xlsx, upload
from .fakes import FakeLLM

PW = "correct horse battery"


def app_with(tmp_path, llm=None, transport=None, **kw):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None, **kw)
    k = Knowledge(s, llm=llm, url_transport=transport)
    return TestClient(create_app(s, k)), k, s


# ----------------------------------------------------------------------------- intent splitting
@pytest.mark.parametrize("q,n", [
    ('How many times does "Anjali Rao" appear, and what is the highest sales?', 2),
    ("Summarize policy.pdf; compare a.txt and b.txt", 2),
    ("What is the refund window? Who approves refunds? Where is the form?", 3),
    ("Which employee has the highest sales and what region is he in?", 0),   # pronoun: depends on the first part
    ("What is the total of sales and expenses?", 0),                           # one question, not two
    ("Tell me about leave", 0), ("hi", 0),
])
def test_split_intents(q, n):
    assert len(split_intents(q)) == n


def test_parallel_fan_out_merges_exact_and_data(tmp_path):
    c, k, s = app_with(tmp_path)
    upload(c, "policy.pdf", make_pdf(["Employees accrue 25 days of annual leave per year. Contact Anjali Rao for help."]))
    upload(c, "sales.xlsx", make_xlsx({"Q1": SALES_ROWS}))
    r = ask(c, 'How many times does "Anjali Rao" appear, and what is the highest sales?')
    assert r["route"] == "parallel" and r["verified"] is True
    br = r["details"]["branches"]
    assert [b["route"] for b in br] == ["exact", "data"] and "Found 1 occurrence" in br[0]["answer"] and "3,400.5" in br[1]["answer"]
    assert "### Exact search" in r["answer"] and "### Data analysis" in r["answer"]
    assert {x["source"] for x in r["citations"]} == {"policy.pdf", "sales.xlsx"} and r["details"]["citation_check"]["accuracy"] == 1.0
    assert any(t.startswith("supervisor: parallel fan-out to exact, data") for t in r["details"]["trace"]) and r["details"]["trace"][-1].startswith("merge")


def test_parallel_branches_really_run_concurrently(tmp_path):
    def script(sy, u):
        if "Answer the question" in sy:
            time.sleep(0.6)
            asked = u.split("Question:")[-1].split("\n")[0].lower()
            return "Expense reports are due within 30 days [1]." if "expense" in asked else "Employees accrue 25 days of annual leave per year [1]."
        return None

    c, k, s = app_with(tmp_path, llm=FakeLLM(script))
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year. Expense reports are due within 30 days.")
    t0 = time.perf_counter()
    r = ask(c, "How many days of annual leave do employees get? How soon are expense reports due?")
    took = time.perf_counter() - t0
    assert r["route"] == "parallel" and len(r["details"]["branches"]) == 2 and took < 1.15, took   # sequential would take >= 1.2 s
    assert "25 days" in r["answer"] and "30 days" in r["answer"]


def test_one_failing_branch_does_not_sink_the_other(tmp_path, monkeypatch):
    c, k, s = app_with(tmp_path)
    upload(c, "sales.xlsx", make_xlsx({"Q1": SALES_ROWS}))
    from app.agents import nodes

    def boom(self, state):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(nodes.Agents, "exact", boom)
    r = ask(c, 'Search for "Bob" in the documents; what is the total sales?')
    br = {b["route"]: b for b in r["details"]["branches"]}
    assert "could not complete this step" in br["exact"]["answer"] and "9,051" in br["data"]["answer"]


def test_parallel_can_be_switched_off(tmp_path):
    c, k, s = app_with(tmp_path, parallel_agents=False)
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    assert ask(c, "How many days of leave do employees get? Who approves leave?")["route"] != "parallel"


# ----------------------------------------------------------------------------- timeouts and retries
def test_node_timeout_returns_an_honest_answer_not_a_hang(tmp_path):
    c, k, s = app_with(tmp_path, llm=FakeLLM(lambda sy, u: time.sleep(1.5) or "late [1]" if "Answer the question" in sy else None), node_timeout_s=0.4, max_retries=0)
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    t0 = time.perf_counter()
    r = ask(c, "How many days of annual leave do employees get?")
    assert time.perf_counter() - t0 < 1.3 and "did not finish within 0.4 seconds" in r["answer"] and not r["verified"]
    assert any("timed out" in t for t in r["details"]["trace"])
    assert 'mka_agent_node_runs_total{node="semantic",outcome="timeout"} 1.0' in k.obs.metrics.render().decode()


class FlakyEmbedder:
    """Delegates to the real embedder but fails the first query embedding like a rate-limited API would."""

    def __init__(self, inner, failures=1):
        self.inner, self.failures, self.calls = inner, failures, 0

    def embed_query(self, text):
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("429 rate limited")
        return self.inner.embed_query(text)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_transient_provider_errors_are_retried_then_surface(tmp_path):
    from app.providers import make_embedder

    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    emb = FlakyEmbedder(make_embedder(s))
    c = TestClient(create_app(s, Knowledge(s, embedder=emb)))
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    r = ask(c, "How many days of annual leave do employees get?")
    assert r["verified"] and "25 days" in r["answer"] and emb.calls >= 2          # one transient failure, retried transparently
    s2 = Settings(data_dir=str(tmp_path / "e"), _env_file=None)
    bad = FlakyEmbedder(make_embedder(s2), failures=99)
    c2 = TestClient(create_app(s2, Knowledge(s2, embedder=bad)))
    upload(c2, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    assert c2.post("/ask", json={"question": "How many days of annual leave do employees get?"}, headers={"X-Session-ID": "s1"}).status_code == 502   # persistent outage surfaces


# ----------------------------------------------------------------------------- metrics and tracing
def test_metrics_endpoint_counts_requests_questions_tools_and_ingest(tmp_path):
    c, k, s = app_with(tmp_path)
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    ask(c, "How many days of annual leave do employees get?")
    ask(c, 'find "annual"')
    body = c.get("/metrics").text
    for needle in ('mka_ingest_total{outcome="ready"} 1.0', 'mka_questions_total{route="semantic",verified="true"} 1.0', 'mka_questions_total{route="exact",verified="true"} 1.0',
                   'mka_tool_calls_total{outcome="ok",tool="hybrid_search"}', 'mka_agent_node_runs_total{node="verify",outcome="ok"}', 'mka_http_requests_total{method="POST",route="/ask",status="200"} 2.0',
                   "mka_citations_total", "mka_http_request_seconds_bucket"):
        assert needle in body or needle.replace('outcome="ok",tool="hybrid_search"', 'tool="hybrid_search",outcome="ok"') in body, needle


def test_metrics_access_control(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, metrics_token="scrape-token-123", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"}).status_code == 200
    adm = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"]
    assert c.get("/metrics", headers={"Authorization": f"Bearer {adm}"}).status_code == 200
    h = {"Authorization": f"Bearer {adm}"}
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=h)
    usr = c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"]
    assert c.get("/metrics", headers={"Authorization": f"Bearer {usr}"}).status_code == 403
    off = TestClient(create_app(Settings(data_dir=str(tmp_path / "e"), metrics_enabled=False, _env_file=None)))
    assert off.get("/metrics").status_code == 404


def test_opentelemetry_spans_for_requests_nodes_and_tools(tmp_path):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s)
    k.obs = Observability(s, tracer_provider=provider)
    c = TestClient(create_app(s, k))
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    ask(c, "How many days of annual leave do employees get?")
    names = [sp.name for sp in exporter.get_finished_spans()]
    assert {"agent.supervisor", "agent.semantic", "agent.verify", "agent.final", "tool.hybrid_search"} <= set(names)
    sem = next(sp for sp in exporter.get_finished_spans() if sp.name == "agent.semantic")
    assert sem.attributes["mka.route"] == "semantic" and sem.status.is_ok or sem.status.status_code.name == "UNSET"


def test_failed_node_marks_its_span_and_langsmith_env_wiring(tmp_path, monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    obs = Observability(Settings(data_dir=str(tmp_path), _env_file=None), tracer_provider=provider)
    with pytest.raises(ValueError):
        with obs.span("x"):
            raise ValueError("bad")
    assert exporter.get_finished_spans()[0].status.status_code.name == "ERROR"
    for k in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    assert setup_langsmith(Settings(data_dir=str(tmp_path), _env_file=None)) is False and "LANGSMITH_API_KEY" not in os.environ
    assert setup_langsmith(Settings(data_dir=str(tmp_path), langsmith_api_key="ls-key", langsmith_project="proj", _env_file=None)) is True
    assert os.environ["LANGSMITH_TRACING"] == "true" and os.environ["LANGSMITH_PROJECT"] == "proj" and os.environ["LANGSMITH_API_KEY"] == "ls-key"
    for k in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT"):
        monkeypatch.delenv(k, raising=False)


# ----------------------------------------------------------------------------- web allow-list
PAGE = b"<html><head><title>News</title></head><body><p>The widget warranty lasts 24 months.</p></body></html>"


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    real = socket.getaddrinfo
    table = {"docs.example.com": "93.184.216.34", "example.com": "93.184.216.34", "other.test": "93.184.216.35"}

    def fake(host, port, *a, **kw):
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(web.socket, "getaddrinfo", fake)

    def handler(req: httpx.Request):
        if req.url.path == "/hop":
            return httpx.Response(302, headers={"location": "https://other.test/page"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=PAGE)

    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="1000/minute", rate_limit_auth="1000/minute", rate_limit_ingest="1000/minute", _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, url_transport=httpx.MockTransport(handler))))
    adm = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"]
    return c, {"Authorization": f"Bearer {adm}", "X-Session-ID": "w"}


def settings_body(**kw):
    return {"retention_days_documents": None, "retention_days_conversations": None, "retention_days_audit": None, "retention_days_reports": None,
            "web_allowed": True, "web_allowed_domains": [], "redact_stored_messages": False, **kw}


def test_web_allow_list_and_separate_web_evidence(web_env):
    c, h = web_env
    q = "What does https://docs.example.com/page say about the widget warranty?"
    open_ = c.post("/ask", json={"question": q}, headers=h).json()
    assert open_["route"] == "web" and "24 months" in open_["answer"] and open_["citations"][0]["origin"] == "web"
    assert c.put("/admin/tenant-settings", json=settings_body(web_allowed_domains=["example.com"]), headers=h).status_code == 200
    ok = c.post("/ask", json={"question": q}, headers=h).json()
    assert "24 months" in ok["answer"]                                        # subdomain of an approved domain
    blocked = c.post("/ask", json={"question": "What does https://other.test/page say about the widget warranty?"}, headers=h).json()
    assert "24 months" not in blocked["answer"] and any("approved web sources" in x for x in blocked["limitations"])
    hop = c.post("/ask", json={"question": "What does https://docs.example.com/hop say about the widget warranty?"}, headers=h).json()
    assert "24 months" not in hop["answer"] and any("redirected" in x for x in hop["limitations"])
    c.put("/admin/tenant-settings", json=settings_body(web_allowed=False), headers=h)
    off = c.post("/ask", json={"question": q}, headers=h).json()
    assert "disabled for your organisation" in off["answer"]


def test_documents_and_web_stay_separate_in_a_parallel_answer(web_env):
    c, h = web_env
    c.post("/sources/upload", files=[("files", ("p.txt", b"Employees accrue 25 days of annual leave per year."))], headers=h)
    r = c.post("/ask", json={"question": "How many days of annual leave do employees get? What does https://docs.example.com/page say about the widget warranty?"}, headers=h).json()
    assert r["route"] == "parallel" or r["route"] == "web"
    if r["route"] == "parallel":
        origins = {x["source"]: x["origin"] for x in r["citations"]}
        assert origins["p.txt"] == "document" and any(o == "web" for o in origins.values())
        assert any("separately" in x for x in r["limitations"]) and "### Web research (external" in r["answer"]


# ----------------------------------------------------------------------------- retention / maintenance
def backdate(k, days):
    old = datetime.now(UTC) - timedelta(days=days)
    with k.db.session() as s:
        for d in s.scalars(select(Document)):
            d.created_at = old
        for cv in s.scalars(select(Conversation)):
            cv.updated_at = old
        for a in s.scalars(select(AuditEvent)):
            a.ts = old
        for j in s.scalars(select(Job)):
            j.updated_at = old


def test_retention_sweeps_respect_each_tenants_policy(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="1000/minute", rate_limit_auth="1000/minute", rate_limit_ingest="1000/minute", _env_file=None)
    k = Knowledge(s)
    c = TestClient(create_app(s, k))

    def tenant(name, email):
        tok = c.post("/auth/signup", json={"tenant_name": name, "email": email, "password": PW}).json()["access_token"]
        return {"Authorization": f"Bearer {tok}", "X-Session-ID": "w"}

    a, b = tenant("Acme", "a@acme.io"), tenant("Beta", "b@beta.io")
    for h in (a, b):
        c.post("/sources/upload", files=[("files", ("p.txt", b"Employees accrue 25 days of annual leave per year."))], headers=h)
        c.post("/ask", json={"question": "How many days of annual leave do employees get?"}, headers=h)
    c.put("/admin/tenant-settings", json=settings_body(retention_days_documents=30, retention_days_conversations=30, retention_days_audit=30), headers=a)   # Beta keeps everything
    backdate(k, 90)
    dry = c.post("/admin/maintenance/run", json={"dry_run": True}, headers=a).json()
    assert dry["dry_run"] and dry["results"]["retention_documents"]["removed"] == 1 and dry["results"]["retention_conversations"]["removed"] == 1
    assert len(c.get("/sources", headers=a).json()) == 1                       # dry run changed nothing
    real = c.post("/admin/maintenance/run", json={"dry_run": False, "tasks": ["retention_documents", "retention_conversations", "retention_audit"]}, headers=a).json()["results"]
    assert real["retention_documents"]["removed"] == 1 and real["retention_conversations"]["removed"] == 1 and real["retention_audit"]["removed"] > 0
    assert c.get("/sources", headers=a).json() == [] and c.get("/conversations", headers=a).json() == []
    assert len(c.get("/sources", headers=b).json()) == 1 and len(c.get("/conversations", headers=b).json()) == 1      # other tenant untouched
    audit = c.get("/admin/audit", headers=a).json()
    assert any(e["action"] == "retention_sweep" for e in audit)               # the sweep itself is auditable and survives
    assert c.post("/admin/maintenance/run", json={"tasks": ["rm_rf"]}, headers=a).status_code == 422


def test_maintenance_roles_and_housekeeping(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="1000/minute", finished_jobs_retention_days=7, _env_file=None)
    k = Knowledge(s)
    c = TestClient(create_app(s, k))
    adm = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"]}
    c.post("/admin/users", json={"email": "m@acme.io", "password": PW, "role": "manager"}, headers=adm)
    mgr = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "m@acme.io", "password": PW}).json()["access_token"]}
    assert c.post("/admin/maintenance/run", json={}, headers=mgr).status_code == 403
    with k.db.session() as ses:
        ses.add(Job(tenant_id="t", user_id="u", workspace="w", kind="file", name="x", status="ready"))
        ses.add(Job(tenant_id="t", user_id="u", workspace="w", kind="file", name="y", status="running"))
    backdate(k, 30)
    res = maintenance.run(k, ["cleanup_jobs", "cleanup_tokens"], dry_run=False)
    assert res["cleanup_jobs"]["removed"] == 1                                # the running job is never removed
    with k.db.session() as ses:
        assert [j.status for j in ses.scalars(select(Job))] == ["running"]
    broken = maintenance.run(k, ["retention_audit", "cleanup_jobs"], dry_run=True)
    assert set(broken) == {"retention_audit", "cleanup_jobs"}


def test_scheduler_round_uses_a_leader_lock(tmp_path):
    from app import scheduler
    from app.security.audit import Auditor

    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s)
    aud = Auditor(k.db, True)

    class FakeRedis:
        def __init__(self):
            self.keys = {}

        def set(self, key, val, nx=False, ex=None):
            if nx and key in self.keys:
                return None
            self.keys[key] = val
            return True

        def delete(self, key):
            self.keys.pop(key, None)

    assert set(scheduler.run_round(k, aud, None, dry_run=True)) == set(maintenance.TASKS)
    r = FakeRedis()
    r.keys["mka:scheduler:lock"] = "other-replica"
    assert scheduler.run_round(k, aud, r) is None                              # another replica is the leader
    r.keys.clear()
    assert scheduler.run_round(k, aud, r) is not None and r.keys == {}         # lock released afterwards
