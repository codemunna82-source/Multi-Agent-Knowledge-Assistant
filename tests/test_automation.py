import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import automation, maintenance
from app.api import create_app
from app.config import Settings
from app.db import Alert, Connector, ReportSchedule
from app.ingestion import web
from app.service import Knowledge

from .conftest import make_pdf

PW = "correct horse battery"


class Env:
    def __init__(self, tmp_path, **kw):
        self.posts = []

        def handler(req: httpx.Request):
            if req.method == "POST":
                self.posts.append((str(req.url), req.read().decode()))
                return httpx.Response(200 if "fail" not in req.url.path else 500)
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><title>T</title><body><p>Remote work is allowed three days.</p></body></html>")

        self.s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="10000/minute", rate_limit_auth="10000/minute", rate_limit_ingest="10000/minute",
                          connector_root=str(tmp_path / "share"), _env_file=None, **kw)
        self.k = Knowledge(self.s, url_transport=httpx.MockTransport(handler))
        self.c = TestClient(create_app(self.s, self.k))
        self.adm = {"Authorization": "Bearer " + self.c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
        self.c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=self.adm)
        self.user = {"Authorization": "Bearer " + self.c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}

    def up(self, name, data, h=None, vis="tenant"):
        r = self.c.post("/sources/upload", files=[("files", (name, data))], data={"visibility": vis}, headers=h or self.adm)
        assert r.status_code == 200, r.text
        return r.json()[0]


@pytest.fixture
def env(tmp_path, monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda host, port, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))] if host.endswith(("example.com", "hooks.test")) else real(host, port, *a, **kw))
    return Env(tmp_path)


# ----------------------------------------------------------------------------- saved searches and alerts
def test_saved_search_alerts_new_documents_and_posts_a_webhook_without_text(env):
    c = env.c
    s = c.post("/saved-searches", json={"term": "Anjali Rao", "webhook_url": "https://hooks.test/in"}, headers=env.user)
    assert s.status_code == 201
    env.up("a.txt", b"Nothing relevant here at all, just ordinary words.")
    assert c.get("/alerts", headers=env.user).json() == []
    env.up("b.txt", b"Contact Anjali Rao for help. Anjali Rao approved the budget.")
    al = c.get("/alerts", headers=env.user).json()
    assert len(al) == 1 and al[0]["source_name"] == "b.txt" and al[0]["count"] == 2 and not al[0]["seen"] and al[0]["locations"]
    assert env.posts and env.posts[0][0] == "https://hooks.test/in" and '"occurrences":2' in env.posts[0][1]
    assert "budget" not in env.posts[0][1] and "Contact" not in env.posts[0][1]               # ids, counts, locations - never document text
    assert c.get("/alerts?unseen=true", headers=env.user).headers["x-total-count"] == "1"
    assert c.post("/alerts/seen", headers=env.user).json() == {"marked": 1} and c.get("/alerts?unseen=true", headers=env.user).json() == []
    assert c.get("/alerts", headers=env.adm).json() == []                                       # alerts belong to the person who set the watch


def test_alerts_respect_document_permissions_and_workspaces(env):
    c = env.c
    c.post("/saved-searches", json={"term": "secret merger"}, headers=env.user)
    env.up("hidden.txt", b"The secret merger is planned for June.", vis="private")           # private to the admin: the watcher must not learn it exists
    assert c.get("/alerts", headers=env.user).json() == []
    env.up("open.txt", b"The secret merger rumour is false.", h={**env.adm, "X-Session-ID": "other"})   # another workspace
    assert c.get("/alerts", headers=env.user).json() == []
    env.up("shared.txt", b"Notes on the secret merger.")
    assert [a["source_name"] for a in c.get("/alerts", headers=env.user).json()] == ["shared.txt"]


def test_saved_search_validation_limits_and_ownership(env):
    c = env.c
    assert c.post("/saved-searches", json={"term": "x"}, headers=env.user).status_code == 422
    assert c.post("/saved-searches", json={"term": "valid term", "webhook_url": "http://127.0.0.1/hook"}, headers=env.user).status_code == 422     # SSRF guard on webhook targets
    assert c.post("/saved-searches", json={"term": "valid term", "webhook_url": "ftp://hooks.test/x"}, headers=env.user).status_code == 422
    sid = c.post("/saved-searches", json={"term": "valid term"}, headers=env.user).json()["id"]
    assert c.delete(f"/saved-searches/{sid}", headers={**env.adm}).status_code == 200         # admins can remove any
    assert c.get("/saved-searches", headers=env.user).json() == []


def test_notify_never_raises_and_reports_failures(env):
    assert automation.notify(env.k, None, {}) == "skipped"
    assert automation.notify(env.k, "https://hooks.test/ok", {"a": 1}) == "sent"
    assert automation.notify(env.k, "https://hooks.test/fail", {"a": 1}) == "HTTP 500"
    assert automation.notify(env.k, "http://169.254.169.254/latest", {"a": 1}).startswith("failed")


# ----------------------------------------------------------------------------- scheduled reports
def test_report_schedule_runs_when_due_and_notifies(env):
    c = env.c
    env.up("p.pdf", make_pdf(["Employees accrue 25 days of annual leave per year."]))
    body = {"name": "Weekly summary", "kind": "summary", "format": "docx", "every_hours": 168, "webhook_url": "https://hooks.test/reports", "params": {"style": "short"}}
    sid = c.post("/report-schedules", json=body, headers=env.adm).json()["id"]
    assert c.post("/report-schedules", json={**body, "every_hours": 0}, headers=env.adm).status_code == 422
    assert c.post("/report-schedules", json={**body, "webhook_url": "http://localhost/x"}, headers=env.adm).status_code == 422
    dry = maintenance.run(env.k, ["run_report_schedules"], dry_run=True)["run_report_schedules"]
    assert dry["due"] == ["Weekly summary"] and c.get("/reports", headers=env.adm).json() == []
    res = maintenance.run(env.k, ["run_report_schedules"])["run_report_schedules"]
    assert res["ran"][0]["status"].startswith("ok: report") and "webhook sent" in res["ran"][0]["status"]
    reps = c.get("/reports", headers=env.adm).json()
    assert len(reps) == 1 and reps[0]["format"] == "docx" and c.get(reps[0]["download_url"], headers=env.adm).status_code == 200
    assert '"event":"report_ready"' in env.posts[-1][1] and "download_path" in env.posts[-1][1] and "Employees accrue" not in env.posts[-1][1]
    again = maintenance.run(env.k, ["run_report_schedules"])["run_report_schedules"]
    assert again["ran"] == []                                                                  # not due again for a week
    with env.k.db.session() as s:
        s.get(ReportSchedule, sid).last_run_at = datetime.now(UTC) - timedelta(hours=200)
    assert len(maintenance.run(env.k, ["run_report_schedules"])["run_report_schedules"]["ran"]) == 1
    listed = c.get("/report-schedules", headers=env.adm).json()[0]
    assert listed["last_status"].startswith("ok") and listed["last_run_at"]
    assert c.post(f"/report-schedules/{sid}/run", headers=env.user).status_code == 404         # other people's schedules are invisible
    assert c.patch(f"/report-schedules/{sid}?enabled=false", headers=env.adm).json()["enabled"] is False
    with env.k.db.session() as s:
        s.get(ReportSchedule, sid).last_run_at = None
    assert maintenance.run(env.k, ["run_report_schedules"])["run_report_schedules"]["ran"] == []   # disabled schedules never run


def test_schedule_failure_is_recorded_not_raised(env):
    sid = env.c.post("/report-schedules", json={"name": "Broken", "kind": "comparison", "every_hours": 1}, headers=env.adm).json()["id"]    # needs two documents
    res = maintenance.run(env.k, ["run_report_schedules"])["run_report_schedules"]["ran"][0]
    assert res["status"].startswith("failed")
    assert env.c.get("/report-schedules", headers=env.adm).json()[0]["last_status"].startswith("failed") and sid


def test_run_now_endpoint(env):
    env.up("p.pdf", make_pdf(["Employees accrue 25 days of annual leave per year."]))
    sid = env.c.post("/report-schedules", json={"name": "Now", "kind": "summary", "every_hours": 24}, headers=env.adm).json()["id"]
    assert env.c.post(f"/report-schedules/{sid}/run", headers=env.adm).json()["status"].startswith("ok")
    assert len(env.c.get("/reports", headers=env.adm).json()) == 1


# ----------------------------------------------------------------------------- connectors
def test_folder_connector_syncs_versions_and_stays_inside_its_root(env, tmp_path):
    share = tmp_path / "share"
    (share / "hr").mkdir(parents=True)
    (share / "hr" / "policy.txt").write_text("Employees accrue 25 days of annual leave per year.")
    (share / "hr" / "notes.exe").write_text("ignored: unsupported type")
    (tmp_path / "secret.txt").write_text("outside the root")
    c = env.c
    assert c.post("/connectors", json={"name": "x", "kind": "folder", "config": {"path": "../"}}, headers=env.adm).status_code == 422
    assert c.post("/connectors", json={"name": "x", "kind": "folder", "config": {"path": str(tmp_path)}}, headers=env.adm).status_code == 422
    assert c.post("/connectors", json={"name": "x", "kind": "folder", "config": {"path": "missing"}}, headers=env.adm).status_code == 422
    assert c.post("/connectors", json={"name": "x", "kind": "folder", "config": {"path": "hr"}}, headers=env.user).status_code == 403          # managers and admins only
    cid = c.post("/connectors", json={"name": "HR share", "kind": "folder", "config": {"path": "hr"}, "every_hours": 6}, headers=env.adm).json()["id"]
    r1 = c.post(f"/connectors/{cid}/sync", headers=env.adm).json()
    assert (r1["ready"], r1["duplicate"], r1["failed"], r1["seen"]) == (1, 0, 0, 1)
    r2 = c.post(f"/connectors/{cid}/sync", headers=env.adm).json()
    assert (r2["ready"], r2["duplicate"]) == (0, 1)                                              # unchanged file: nothing re-indexed
    (share / "hr" / "policy.txt").write_text("Employees accrue 30 days of annual leave per year.")
    assert c.post(f"/connectors/{cid}/sync", headers=env.adm).json()["ready"] == 1               # changed content -> version 2
    src = [x for x in c.get("/sources", headers=env.adm).json() if x["name"] == "policy.txt"]
    assert len(src) == 1 and src[0]["version"] == 2
    assert c.get("/connectors", headers=env.adm).json()[0]["last_result"]["ready"] == 1


def test_folder_connector_ignores_symlinks_that_escape_and_is_disabled_without_a_root(env, tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    (tmp_path / "outside.txt").write_text("private data outside the share")
    (share / "link.txt").symlink_to(tmp_path / "outside.txt")
    cid = env.c.post("/connectors", json={"name": "L", "kind": "folder", "config": {"path": "."}}, headers=env.adm).json()["id"]
    assert env.c.post(f"/connectors/{cid}/sync", headers=env.adm).json()["seen"] == 0
    off = Env(tmp_path / "n", )
    off.s.connector_root = ""
    assert off.c.post("/connectors", json={"name": "L", "kind": "folder", "config": {"path": "."}}, headers=off.adm).status_code == 422


def test_url_connector_and_scheduler_sync(env):
    cid = env.c.post("/connectors", json={"name": "Wiki", "kind": "urls", "config": {"urls": ["https://example.com/a"]}, "every_hours": 1}, headers=env.adm).json()["id"]
    assert env.c.post("/connectors", json={"name": "Bad", "kind": "urls", "config": {"urls": ["http://127.0.0.1/"]}}, headers=env.adm).status_code == 422
    assert env.c.post("/connectors", json={"name": "S3", "kind": "s3", "config": {"bucket": "b"}}, headers=env.adm).status_code == 422     # boto3 is optional and not installed here
    res = maintenance.run(env.k, ["sync_connectors"])["sync_connectors"]["ran"]
    assert res == [{"connector": "Wiki", "ready": 1, "duplicate": 0, "failed": 0, "seen": 1, "errors": 0}]
    assert maintenance.run(env.k, ["sync_connectors"])["sync_connectors"]["ran"] == []           # not due for another hour
    with env.k.db.session() as s:
        s.get(Connector, cid).last_run_at = datetime.now(UTC) - timedelta(hours=2)
    assert maintenance.run(env.k, ["sync_connectors"])["sync_connectors"]["ran"][0]["duplicate"] == 1
    assert [x["name"] for x in env.c.get("/sources", headers=env.adm).json()] == ["https://example.com/a"]


# ----------------------------------------------------------------------------- annotations
def test_annotations_private_shared_and_permissioned(env):
    src = env.up("p.pdf", make_pdf(["Employees accrue 25 days of annual leave per year.", "Second page."]))["source"]
    c = env.c
    mine = c.post("/annotations", json={"source_id": src["id"], "loc": {"page": 1}, "quote": "25 days", "note": "check with HR", "kind": "comment"}, headers=env.user).json()
    shared = c.post("/annotations", json={"source_id": src["id"], "loc": {"page": 2}, "note": "important", "kind": "bookmark", "shared": True}, headers=env.adm).json()
    assert [a["note"] for a in c.get(f"/annotations?source_id={src['id']}", headers=env.user).json()] == ["check with HR", "important"]
    assert [a["note"] for a in c.get(f"/annotations?source_id={src['id']}", headers=env.adm).json()] == ["important"]          # the user's private note stays private
    assert c.delete(f"/annotations/{shared['id']}", headers=env.user).status_code == 404       # cannot delete somebody else's
    assert c.delete(f"/annotations/{mine['id']}", headers=env.adm).status_code == 200          # admin may
    assert c.post("/annotations", json={"source_id": "0" * 32, "loc": {"page": 1}}, headers=env.user).status_code == 404
    assert c.post("/annotations", json={"source_id": src["id"], "loc": {}}, headers=env.user).status_code == 422
    assert c.post("/annotations", json={"source_id": src["id"], "loc": {"page": {"x": 1}}}, headers=env.user).status_code == 422
    hidden = env.up("h.txt", b"private notes", vis="private")["source"]
    assert c.post("/annotations", json={"source_id": hidden["id"], "loc": {"line": 1}}, headers=env.user).status_code == 404       # cannot annotate what you cannot read
    assert c.get(f"/annotations?source_id={hidden['id']}", headers=env.user).status_code == 404


# ----------------------------------------------------------------------------- chunking lab
def test_chunking_lab_compares_sizes(env):
    text = "\n\n".join(f"Paragraph {i}. " + "Sentence about policy and leave. " * 12 for i in range(12))
    src = env.up("long.txt", text.encode())["source"]
    r = env.c.post("/learn/chunking", json={"source_id": src["id"]}, headers=env.adm).json()
    rows = {x["size"]: x for x in r["rows"]}
    assert rows[400]["chunks"] > rows[1000]["chunks"] > rows[2500]["chunks"] >= 1 and rows[400]["avg_chars"] < rows[2500]["avg_chars"] and rows[400]["samples"][0]["text"]
    assert env.c.post("/learn/chunking", json={"source_id": src["id"], "settings": [{"size": 50, "overlap": 0}]}, headers=env.adm).status_code == 422
    assert env.c.post("/learn/chunking", json={"source_id": src["id"], "settings": [{"size": 500, "overlap": 400}]}, headers=env.adm).status_code == 422
    assert env.c.post("/learn/chunking", json={"source_id": "0" * 32}, headers=env.adm).status_code == 404


def test_tenant_isolation_of_automation_objects(env):
    env.c.post("/saved-searches", json={"term": "secret term"}, headers=env.user)
    other = {"Authorization": "Bearer " + env.c.post("/auth/signup", json={"tenant_name": "Beta", "email": "b@beta.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
    assert env.c.get("/saved-searches", headers=other).json() == [] and env.c.get("/alerts", headers=other).json() == [] and env.c.get("/connectors", headers=other).json() == []
    env.c.post("/ingest-nothing", headers=other)
    with env.k.db.session() as s:
        assert s.scalars(select(Alert)).all() == []
