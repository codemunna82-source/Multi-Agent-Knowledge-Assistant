"""Encrypted MFA seeds, Slack/e-mail notifications, SIEM shipping, admin insights."""
import json
import smtplib

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import automation, maintenance, siem
from app.api import create_app
from app.config import Settings
from app.core import IngestError
from app.db import AuditEvent, UserMfa
from app.security import secretbox, totp
from app.service import Knowledge

from .conftest import make_pdf

PW = "correct horse battery"


def build(tmp_path, transport=None, **kw):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", rate_limit_ask="10000/minute", rate_limit_ingest="10000/minute",
                 allow_private_urls=False, _env_file=None, **kw)
    k = Knowledge(s, url_transport=transport)
    c = TestClient(create_app(s, k))
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    return c, k, s, {"Authorization": "Bearer " + t["access_token"], "X-Session-ID": "w"}


# ----------------------------------------------------------------------------- secret box + MFA
def test_secretbox_roundtrip_plaintext_migration_and_failures():
    key = Fernet.generate_key().decode()
    s = Settings(data_key=key, _env_file=None)
    enc = secretbox.seal(s, "JBSWY3DPEHPK3PXP")
    assert enc.startswith("enc1:") and "JBSWY3DPEHPK3PXP" not in enc and secretbox.open_(s, enc) == "JBSWY3DPEHPK3PXP"
    off = Settings(_env_file=None)
    assert secretbox.seal(off, "ABC") == "ABC" and secretbox.open_(s, "ABC") == "ABC"            # plaintext written before a key existed stays readable
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_(off, enc)                                                                  # encrypted value without the key: error, not a guess
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.open_(Settings(data_key=Fernet.generate_key().decode(), _env_file=None), enc)    # wrong key
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.seal(Settings(data_key="not-a-key", _env_file=None), "x")


def test_mfa_seed_is_encrypted_in_the_database_and_login_still_works(tmp_path):
    c, k, s, h = build(tmp_path, data_key=Fernet.generate_key().decode())
    sec = c.post("/auth/mfa/setup", headers=h).json()["secret"]
    c.post("/auth/mfa/enable", json={"code": totp.totp(sec)}, headers=h)
    with k.db.session() as db:
        stored = db.scalar(select(UserMfa.secret))
    assert stored.startswith("enc1:") and sec not in stored and len(stored) > 64
    ok = c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": totp.totp(sec, __import__("time").time() + 30)})
    assert ok.status_code == 200


def test_migration_head_allows_long_encrypted_seed(tmp_path):
    from sqlalchemy import inspect

    c, k, s, h = build(tmp_path)
    col = [x for x in inspect(k.db.engine).get_columns("user_mfa") if x["name"] == "secret"][0]
    assert getattr(col["type"], "length", 255) >= 255


# ----------------------------------------------------------------------------- notifications
class Smtp:
    sent = []

    def __init__(self, host, port, timeout=0):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, u, p):
        self.cred = (u, p)

    def send_message(self, msg):
        Smtp.sent.append(msg)


def test_mailto_target_is_validated_and_delivered_without_document_text(tmp_path, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", Smtp)
    Smtp.sent.clear()
    c, k, s, h = build(tmp_path, smtp_host="smtp.example.com", smtp_user="u", smtp_password="pw")
    assert c.post("/saved-searches", json={"term": "indemnity", "webhook_url": "mailto:not an address"}, headers=h).status_code == 422
    assert c.post("/saved-searches", json={"term": "indemnity", "webhook_url": "mailto:legal@acme.io"}, headers=h).status_code == 201
    c.post("/sources/upload", files=[("files", ("c.pdf", make_pdf(["The indemnity clause limits liability. Indemnity applies twice."])))], headers=h)
    assert len(Smtp.sent) == 1
    m = Smtp.sent[0]
    assert m["To"] == "legal@acme.io" and "indemnity" in m["Subject"].lower() and "c.pdf" in m.get_content()
    assert "limits liability" not in m.get_content()                                              # identifiers and counts only


def test_mailto_is_refused_without_smtp_and_failures_never_raise(tmp_path, monkeypatch):
    c, k, s, h = build(tmp_path)
    assert c.post("/saved-searches", json={"term": "x", "webhook_url": "mailto:a@b.io"}, headers=h).status_code == 422
    assert automation.notify(k, "mailto:a@b.io", {"event": "x"}).startswith("failed")
    k.settings.smtp_host = "smtp.example.com"

    def boom(*a, **kw):
        raise smtplib.SMTPException("down")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    assert automation.notify(k, "mailto:a@b.io", {"event": "x"}).startswith("failed: down")
    with pytest.raises(IngestError):
        automation.webhook_url_ok(k, "mailto:a@b.io\nBcc: evil@x.io")


def test_slack_webhooks_get_slack_format_others_keep_the_event_payload(tmp_path, monkeypatch):
    posts = []
    c, k, s, h = build(tmp_path, transport=httpx.MockTransport(lambda r: (posts.append((str(r.url), json.loads(r.content))), httpx.Response(200))[1]))
    monkeypatch.setattr(automation.web, "resolve_public", lambda url, allow=False: None)
    ev = {"event": "saved_search_match", "term": "indemnity", "document": "c.pdf", "occurrences": 2, "locations": ["page 1"]}
    assert automation.notify(k, "https://hooks.slack.com/services/T/B/x", ev) == "sent"
    assert automation.notify(k, "https://example.com/hook", ev) == "sent"
    assert list(posts[0][1]) == ["text"] and "indemnity" in posts[0][1]["text"] and "c.pdf" in posts[0][1]["text"]
    assert posts[1][1] == ev


# ----------------------------------------------------------------------------- SIEM
def test_siem_ships_new_events_once_keeps_cursor_on_failure_and_formats_hec(tmp_path):
    got, state = [], {"status": 200}

    def handler(req):
        got.append((req.headers, req.content.decode()))
        return httpx.Response(state["status"])

    c, k, s, h = build(tmp_path, transport=httpx.MockTransport(handler), siem_url="https://siem.example.com/in", siem_token="tok", siem_batch=2)
    with k.db.session() as db:
        total = len(db.scalars(select(AuditEvent)).all())
    assert total >= 1
    state["status"] = 503
    r = siem.ship(k)
    assert r["error"].startswith("collector answered HTTP 503") and r["cursor"] == 0                  # nothing lost: cursor did not move
    state["status"] = 200
    r = siem.ship(k)
    assert r["sent"] == total and got[-1][0]["authorization"] == "Bearer tok"
    first = json.loads(got[-1][1].splitlines()[0])
    assert {"id", "ts", "action", "outcome"} <= set(first)
    n = len(got)
    assert siem.ship(k)["sent"] == 0 and len(got) == n                                              # already shipped: nothing is re-sent
    c.get("/auth/me", headers=h)
    c.post("/auth/login", json={"email": "a@acme.io", "password": PW})
    assert siem.ship(k)["sent"] >= 1
    k.settings.siem_format = "splunk_hec"
    k.settings.siem_token = __import__("pydantic").SecretStr("hec")
    (tmp_path / "d" / "siem_cursor.json").unlink()
    siem.ship(k)
    assert got[-1][0]["authorization"] == "Splunk hec" and "sourcetype" in got[-1][1]


def test_ship_audit_is_a_registered_maintenance_task_and_skips_when_unconfigured(tmp_path):
    c, k, s, h = build(tmp_path)
    assert "ship_audit" in maintenance.TASKS
    assert maintenance.run(k, ["ship_audit"])["ship_audit"]["skipped"].startswith("MKA_SIEM_URL")


# ----------------------------------------------------------------------------- insights
def test_insights_aggregate_counts_for_admins_only(tmp_path):
    c, k, s, h = build(tmp_path)
    c.post("/sources/upload", files=[("files", ("p.pdf", make_pdf(["Employees accrue 25 days of annual leave per year."])))], headers=h)
    for q in ("How many days of annual leave?", 'find "annual"', "What is the airspeed of a swallow?"):
        assert c.post("/ask", json={"question": q}, headers=h).status_code == 200
    c.post("/feedback", json={"rating": -1, "route": "semantic"}, headers=h)
    c.post("/ask", json={"question": "private one", "incognito": True}, headers=h)
    j = c.get("/admin/insights?days=7", headers=h).json()
    assert j["answers"] == 3 and sum(j["routes"].values()) == 3 and j["feedback"] == {"up": 0, "down": 1, "down_by_route": {"semantic": 1}}
    assert j["top_sources"][0]["source"] == "p.pdf" and 0 <= j["verified_rate"] <= 1 and "question" not in json.dumps(j).lower().replace("incognito questions", "")
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=h)
    u = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
    assert c.get("/admin/insights", headers=u).status_code == 403
