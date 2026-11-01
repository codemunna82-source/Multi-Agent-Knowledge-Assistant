"""Phase P1: Alembic migrations, PostgreSQL document registry (dedupe, versions, ACL), roles, refresh tokens, pagination, secrets files."""
import os
import threading
import time
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import create_app
from app.config import Settings
from app.db import Base, Database, RefreshToken, migrate
from app.ingestion import web
from app.service import Knowledge
from app.storage import Scope


PW = "correct horse battery"
H = {"X-Session-ID": "w1"}
ROOT = Path(__file__).resolve().parents[1]


def alembic_cfg(url):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["url"] = url
    return cfg


# ------------------------------------------------------------------------------------------- migrations
def test_migrations_apply_match_models_and_migrate_roles(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    command.upgrade(alembic_cfg(url), "0001")
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO tenants(id,name,created_at) VALUES('t1','T','2026-01-01')"))
        for uid, role in (("u1", "viewer"), ("u2", "editor"), ("u3", "admin")):
            c.execute(text(f"INSERT INTO users(id,tenant_id,email,password_hash,role,is_active,created_at) VALUES('{uid}','t1','{uid}@x.io','h','{role}',1,'2026-01-01')"))
        c.execute(text("INSERT INTO conversations(id,tenant_id,user_id,workspace,title,summary_upto,created_at,updated_at) VALUES('c1','t1','u1','w','t',0,'2026-01-01','2026-01-01')"))
    command.upgrade(alembic_cfg(url), "head")
    with eng.connect() as c:
        assert dict(c.execute(text("SELECT id, role FROM users")).all()) == {"u1": "user", "u2": "manager", "u3": "admin"}  # v2.0 roles migrated
        assert c.execute(text("SELECT memory_enabled FROM conversations")).scalar() in (1, True)  # new NOT NULL column back-filled
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == [], f"models and migrations have drifted: {diff}"
    command.downgrade(alembic_cfg(url), "0001")
    with eng.connect() as c:
        assert dict(c.execute(text("SELECT id, role FROM users")).all()) == {"u1": "viewer", "u2": "editor", "u3": "admin"}
    command.upgrade(alembic_cfg(url), "head")


def test_database_can_run_migrations_on_start(tmp_path):
    url = f"sqlite:///{tmp_path}/n.db"
    db = Database(url, run_migrations=True)
    with db.engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
    migrate(url)  # idempotent


@pytest.mark.skipif(not os.environ.get("MKA_TEST_PG_URL"), reason="set MKA_TEST_PG_URL")
def test_migrations_on_postgres_match_models():
    url = os.environ["MKA_TEST_PG_URL"]
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(alembic_cfg(url), "head")
    with eng.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []
        idx = {r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public'")).all()}
    assert {"ix_documents_scope_current", "ix_documents_scope_hash", "ix_audit_tenant_ts", "ix_jobs_tenant_created"} <= idx
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))


# ------------------------------------------------------------------------------------------- helpers
@pytest.fixture
def app_pair(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="f" * 40, rate_limit_ask="1000/minute", rate_limit_ingest="1000/minute", rate_limit_auth="1000/minute",
                 _env_file=None)
    return TestClient(create_app(s)), s


def signup(c, tenant="Tenant X", email="admin@x.io"):
    r = c.post("/auth/signup", json={"tenant_name": tenant, "email": email, "password": PW})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()


def add_user(c, admin_h, email, role):
    r = c.post("/admin/users", json={"email": email, "password": PW, "role": role}, headers=admin_h)
    assert r.status_code == 201, r.text
    tok = c.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, r.json()


def up(c, h, name, data, **form):
    r = c.post("/sources/upload", files=[("files", (name, data))], data=form, headers={**h, **H})
    assert r.status_code == 200, r.text
    return r.json()[0]


def ask(c, h, q, **kw):
    r = c.post("/ask", json={"question": q, **kw}, headers={**h, **H})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------------- duplicates and versions
def test_duplicate_upload_is_detected_not_reingested(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    first = up(c, h, "policy.txt", b"Employees accrue 25 days of leave.")
    dup = up(c, h, "copy-of-policy.txt", b"Employees accrue 25 days of leave.")  # same bytes, different name
    assert first["status"] == "ready" and dup["status"] == "duplicate" and dup["duplicate_of"] == first["source"]["id"] and "Identical" in dup["error"]
    assert len(c.get("/sources", headers={**h, **H}).json()) == 1
    forced = up(c, h, "copy-of-policy.txt", b"Employees accrue 25 days of leave.", allow_duplicate="true")
    assert forced["status"] == "ready" and len(c.get("/sources", headers={**h, **H}).json()) == 2


def test_text_identical_but_bytes_different_is_flagged(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    up(c, h, "a.txt", b"Same words here.\n")
    r = up(c, h, "b.txt", b"Same   words\nhere.")
    assert r["status"] == "ready" and any("identical to 'a.txt'" in w for w in r["source"]["warnings"])


def test_new_content_under_same_name_creates_a_version(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    v1 = up(c, h, "contract.txt", b"The notice period is thirty days.")["source"]
    v2 = up(c, h, "contract.txt", b"The notice period is ninety days.")["source"]
    assert (v1["version"], v2["version"]) == (1, 2) and v1["doc_key"] == v2["doc_key"] and v2["is_current"]
    listed = c.get("/sources", headers={**h, **H}).json()
    assert [s["id"] for s in listed] == [v2["id"]]  # superseded versions are not listed ...
    assert len(c.get("/sources?include_versions=true", headers={**h, **H}).json()) == 2
    assert "ninety" in ask(c, h, "What is the notice period?")["answer"] and "thirty" not in ask(c, h, "What is the notice period?")["answer"]  # ... nor searched
    assert ask(c, h, 'find "thirty"')["details"]["count"] == 0
    vs = c.get(f"/sources/{v2['id']}/versions", headers={**h, **H}).json()
    assert [v["version"] for v in vs] == [2, 1] and [v["is_current"] for v in vs] == [True, False]
    # roll back
    assert c.post(f"/sources/{v1['id']}/make-current", headers={**h, **H}).json()["is_current"] is True
    assert ask(c, h, 'find "thirty"')["details"]["count"] == 1 and ask(c, h, 'find "ninety"')["details"]["count"] == 0
    # deleting the current version restores the other one
    assert c.delete(f"/sources/{v1['id']}", headers={**h, **H}).status_code == 200
    assert [s["version"] for s in c.get("/sources", headers={**h, **H}).json()] == [2]
    assert ask(c, h, 'find "ninety"')["details"]["count"] == 1


def test_delete_all_versions_and_prune(app_pair, tmp_path):
    c, s = app_pair
    h, _ = signup(c)
    for i in range(4):
        up(c, h, "doc.txt", f"revision number {i} of the document".encode())
    c.app.state.knowledge.settings.max_versions_per_document = 2
    up(c, h, "doc.txt", b"revision number 99 of the document")
    assert len(c.get("/sources?include_versions=true", headers={**h, **H}).json()) == 2  # oldest versions pruned (content + vectors)
    cur = c.get("/sources", headers={**h, **H}).json()[0]
    r = c.delete(f"/sources/{cur['id']}?all_versions=true", headers={**h, **H})
    assert r.json()["all_versions"] is True and c.get("/sources?include_versions=true", headers={**h, **H}).json() == []
    assert not list((tmp_path / "d" / "tenants").rglob("units.jsonl"))


def test_concurrent_identical_uploads_yield_one_document(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s)
    scope, results = Scope("t", "w"), []
    for i in range(4):
        (tmp_path / f"f{i}.txt").write_bytes(b"identical content shared by four racing uploads")

    def go(i):
        results.append(k.ingest_file(scope, tmp_path / f"f{i}.txt", f"f{i}.txt")["status"])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == ["duplicate", "duplicate", "duplicate", "ready"]
    assert len(k.store(scope).list_sources()) == 1


def test_async_job_reports_duplicate(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    up(c, h, "a.txt", b"duplicate detection in the queue")
    jid = c.post("/sources/upload?async=true", files=[("files", ("a2.txt", b"duplicate detection in the queue"))], headers={**h, **H}).json()[0]["job_id"]
    for _ in range(100):
        j = c.get(f"/jobs/{jid}", headers={**h, **H}).json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert j["status"] == "duplicate" and "Identical" in j["error"] and j["source_id"]


def test_url_unchanged_is_duplicate_changed_is_new_version(tmp_path, monkeypatch):
    import socket

    page = {"body": b"<html><title>T</title><body><p>Price is 10 dollars.</p></body></html>"}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, headers={"content-type": "text/html"}, content=page["body"]))
    real = socket.getaddrinfo
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda h, p, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", p))] if h == "example.com" else real(h, p, *a, **kw))
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s, url_transport=transport)
    scope = Scope("t", "w")
    a = k.ingest_url(scope, "https://example.com/p")
    b = k.ingest_url(scope, "https://example.com/p")
    assert a["status"] == "ready" and b["status"] == "duplicate" and a["source"]["version"] == 1
    page["body"] = b"<html><title>T</title><body><p>Price is 12 dollars.</p></body></html>"
    c = k.ingest_url(scope, "https://example.com/p")
    assert c["status"] == "ready" and c["source"]["version"] == 2 and [m["version"] for m in k.store(scope).list_sources()] == [2]


def test_reindex_keeps_identity_and_version(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    src = up(c, h, "a.txt", b"reindex me please")["source"]
    r = c.post(f"/sources/{src['id']}/reindex", headers={**h, **H}).json()
    assert r["status"] == "ready" and r["source"]["id"] == src["id"] and r["source"]["version"] == 1 and r["source"]["doc_key"] == src["doc_key"]


# ------------------------------------------------------------------------------------------- document permissions
def test_restricted_sharing_with_users_and_roles(app_pair):
    c, _ = app_pair
    admin, _ = signup(c)
    mgr, mu = add_user(c, admin, "mgr@x.io", "manager")
    u1, u1_user = add_user(c, admin, "u1@x.io", "user")
    u2, _ = add_user(c, admin, "u2@x.io", "user")
    src = up(c, mgr, "plan.txt", b"The restructuring plan names Anjali Rao.")["source"]
    names = lambda h: [s["name"] for s in c.get("/sources", headers={**h, **H}).json()]  # noqa: E731
    assert names(u1) == ["plan.txt"]  # tenant-wide by default
    assert c.put(f"/sources/{src['id']}/sharing", json={"visibility": "restricted", "users": [u1_user["id"]]}, headers={**mgr, **H}).status_code == 200
    assert names(u1) == ["plan.txt"] and names(u2) == [] and names(admin) == ["plan.txt"] and names(mgr) == ["plan.txt"]
    assert c.get(f"/sources/{src['id']}", headers={**u2, **H}).status_code == 404
    hidden = ask(c, u2, "Does Anjali Rao appear?")  # u2 can see no document at all, so nothing is searched
    assert hidden["details"].get("count", 0) == 0 and "plan.txt" not in str(hidden) and not hidden["citations"]
    assert ask(c, u1, "Does Anjali Rao appear?")["details"]["count"] == 1
    # roles
    c.put(f"/sources/{src['id']}/sharing", json={"visibility": "restricted", "roles": ["viewer"]}, headers={**mgr, **H})  # legacy name accepted
    assert names(u1) == ["plan.txt"] and names(u2) == ["plan.txt"]
    got = c.get(f"/sources/{src['id']}/sharing", headers={**mgr, **H}).json()
    assert got["visibility"] == "restricted" and got["roles"] == ["user"] and got["owner_id"] == mu["id"]
    c.put(f"/sources/{src['id']}/sharing", json={"visibility": "private"}, headers={**mgr, **H})
    assert names(u1) == [] and names(mgr) == ["plan.txt"]


def test_sharing_rules(app_pair):
    c, _ = app_pair
    admin, _ = signup(c)
    mgr, _ = add_user(c, admin, "mgr@x.io", "manager")
    mgr2, _ = add_user(c, admin, "mgr2@x.io", "manager")
    usr, _ = add_user(c, admin, "usr@x.io", "user")
    other_admin, other = signup(c, "Other Co", "o@o.io")
    src = up(c, mgr, "a.txt", b"sharing rules document")["source"]
    body = {"visibility": "restricted", "users": []}
    assert c.put(f"/sources/{src['id']}/sharing", json=body, headers={**usr, **H}).status_code == 403  # users cannot share
    assert c.put(f"/sources/{src['id']}/sharing", json=body, headers={**mgr2, **H}).status_code == 403  # not the owner
    assert c.put(f"/sources/{src['id']}/sharing", json={**body, "users": [other["user"]["id"]]}, headers={**admin, **H}).status_code == 422  # other tenant's user
    assert c.put(f"/sources/{src['id']}/sharing", json={"visibility": "public"}, headers={**admin, **H}).status_code == 422
    assert c.put(f"/sources/{src['id']}/sharing", json={"visibility": "restricted", "roles": ["superuser"]}, headers={**admin, **H}).status_code == 422
    assert c.put(f"/sources/{src['id']}/sharing", json=body, headers={**admin, **H}).status_code == 200  # admin may
    assert c.get(f"/sources/{src['id']}/sharing", headers={**other_admin, **H}).status_code == 404


# ------------------------------------------------------------------------------------------- roles
def test_role_names_and_legacy_aliases(app_pair):
    c, _ = app_pair
    admin, _ = signup(c)
    _, legacy_viewer = add_user(c, admin, "v@x.io", "viewer")
    _, legacy_editor = add_user(c, admin, "e@x.io", "editor")
    assert legacy_viewer["role"] == "user" and legacy_editor["role"] == "manager"
    assert c.post("/admin/users", json={"email": "z@x.io", "password": PW, "role": "root"}, headers=admin).status_code == 422
    assert {u["role"] for u in c.get("/admin/users", headers=admin).json()} == {"admin", "user", "manager"}
    usr, _ = add_user(c, admin, "u@x.io", "user")
    mgr, _ = add_user(c, admin, "m@x.io", "manager")
    files = [("files", ("a.txt", b"role matrix"))]
    assert c.post("/sources/upload", files=files, headers={**usr, **H}).status_code == 403  # user: read/ask only
    assert c.post("/sources/upload", files=files, headers={**mgr, **H}).status_code == 200  # manager: ingest
    assert c.get("/admin/users", headers=mgr).status_code == 403 and c.get("/admin/audit", headers=mgr).status_code == 403  # admin only
    assert c.post("/ask", json={"question": "hi"}, headers={**usr, **H}).status_code == 200
    assert c.post("/eval/run", json={"sample": True}, headers={**usr, **H}).status_code == 403


# ------------------------------------------------------------------------------------------- refresh tokens
def test_refresh_rotation_cookie_and_reuse_detection(app_pair):
    c, s = app_pair
    h, body = signup(c)
    assert body["refresh_token"] and len(body["refresh_token"]) > 40
    ck = [v for k, v in c.cookies.items() if k == "mka_refresh"]
    assert ck and ck[0] == body["refresh_token"]
    raw = c.post("/auth/login", json={"email": "admin@x.io", "password": PW})
    sc = raw.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/auth" in sc
    r1 = raw.json()["refresh_token"]
    # rotate (body)
    n = c.post("/auth/refresh", json={"refresh_token": r1})
    assert n.status_code == 200 and n.json()["refresh_token"] != r1
    r2 = n.json()["refresh_token"]
    assert c.get("/auth/me", headers={"Authorization": "Bearer " + n.json()["access_token"]}).status_code == 200
    # replaying the already-rotated token = theft signal: it fails AND revokes the whole family (including the newest token)
    reuse = c.post("/auth/refresh", json={"refresh_token": r1})
    assert reuse.status_code == 401 and "reuse" in reuse.json()["detail"].lower()
    assert c.post("/auth/refresh", json={"refresh_token": r2}).status_code == 401
    audit = c.get("/admin/audit?action=refresh_reuse_detected", headers=h).json()
    assert audit and audit[0]["outcome"] == "denied"
    assert c.post("/auth/refresh", json={"refresh_token": "nonsense"}).status_code == 401
    assert c.post("/auth/refresh", json={}).status_code == 401


def test_refresh_via_cookie_expiry_disabled_user_and_logout(app_pair):
    c, s = app_pair
    admin, _ = signup(c)
    _, usr = add_user(c, admin, "u@x.io", "user")
    c.cookies.clear()
    login = c.post("/auth/login", json={"email": "u@x.io", "password": PW})
    assert c.post("/auth/refresh").status_code == 200  # cookie only, no body
    # role changes are visible after a refresh
    c.patch(f"/admin/users/{usr['id']}", json={"role": "manager"}, headers=admin)
    new = c.post("/auth/refresh").json()
    assert new["user"]["role"] == "manager"
    # logout revokes the family
    access = {"Authorization": "Bearer " + new["access_token"]}
    assert c.post("/auth/logout", headers=access).status_code == 200
    assert c.post("/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401
    assert c.get("/auth/me", headers=access).status_code == 401
    # expiry
    tok = c.post("/auth/login", json={"email": "u@x.io", "password": PW}).json()["refresh_token"]
    with c.app.state.svc.db.session() as ses:
        for row in ses.query(RefreshToken).all():
            row.expires_at = row.expires_at.replace(year=2000)
    assert c.post("/auth/refresh", json={"refresh_token": tok}).status_code == 401
    # disabled account
    fresh = c.post("/auth/login", json={"email": "u@x.io", "password": PW}).json()["refresh_token"]
    c.patch(f"/admin/users/{usr['id']}", json={"is_active": False}, headers=admin)
    assert c.post("/auth/refresh", json={"refresh_token": fresh}).status_code == 401


def test_refresh_tokens_are_stored_hashed(app_pair):
    c, _ = app_pair
    _, body = signup(c)
    with c.app.state.svc.db.session() as ses:
        hashes = [r.token_hash for r in ses.query(RefreshToken).all()]
    assert body["refresh_token"] not in hashes and all(len(h) == 64 for h in hashes)


def test_access_token_lifetime_is_short(app_pair):
    c, s = app_pair
    _, body = signup(c)
    assert body["expires_in"] == 15 * 60 == s.access_token_minutes * 60


# ------------------------------------------------------------------------------------------- pagination
def test_pagination_headers(app_pair):
    c, _ = app_pair
    h, _ = signup(c)
    for i in range(5):
        up(c, h, f"doc{i}.txt", f"distinct document number {i} with words".encode())
    r = c.get("/sources?limit=2&offset=1", headers={**h, **H})
    assert len(r.json()) == 2 and r.headers["x-total-count"] == "5"
    assert [s["name"] for s in c.get("/sources?limit=2&offset=4", headers={**h, **H}).json()] == ["doc4.txt"]
    assert c.get("/sources?limit=0", headers={**h, **H}).status_code == 422 and c.get("/sources?limit=500", headers={**h, **H}).status_code == 422
    assert len(c.get("/sources?q=DOC3", headers={**h, **H}).json()) == 1 and len(c.get("/sources?kind=pdf", headers={**h, **H}).json()) == 0


# ------------------------------------------------------------------------------------------- upgrade path, secrets
def test_backfill_registry_from_v2_disk_layout(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s)
    scope = Scope("t1", "w1")
    (tmp_path / "a.txt").write_text("legacy document content")
    assert k.ingest_file(scope, tmp_path / "a.txt", "a.txt")["status"] == "ready"
    k.registry.delete_scope("t1")  # simulate a v2.0 deployment: files on disk, no registry rows
    assert k.store(scope).list_sources() == []
    assert k.registry.backfill_from_disk(s.data_dir) == 1
    assert k.registry.backfill_from_disk(s.data_dir) == 0  # idempotent
    assert [m["name"] for m in k.store(scope).list_sources()] == ["a.txt"]


def test_secrets_can_come_from_files(tmp_path, monkeypatch):
    f = tmp_path / "jwt"
    f.write_text("s3cret-from-file-" + "x" * 30 + "\n")
    monkeypatch.setenv("MKA_JWT_SECRET_FILE", str(f))
    monkeypatch.delenv("MKA_JWT_SECRET", raising=False)
    s = Settings(data_dir=str(tmp_path), _env_file=None)
    assert s.secret("jwt_secret") == "s3cret-from-file-" + "x" * 30
    monkeypatch.setenv("MKA_JWT_SECRET", "explicit-wins-" + "y" * 30)  # an explicit value beats the file
    assert Settings(data_dir=str(tmp_path), _env_file=None).secret("jwt_secret").startswith("explicit-wins")
    monkeypatch.delenv("MKA_JWT_SECRET")
    monkeypatch.setenv("MKA_JWT_SECRET_FILE", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        Settings(data_dir=str(tmp_path), _env_file=None)


@pytest.mark.skipif(not os.environ.get("MKA_TEST_PG_URL"), reason="set MKA_TEST_PG_URL")
def test_registry_flow_on_postgres(tmp_path):
    url = os.environ["MKA_TEST_PG_URL"]
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    s = Settings(data_dir=str(tmp_path / "d"), database_url=url, auto_migrate=True, auth_enabled=True, jwt_secret="p" * 40, rate_limit_ingest="1000/minute", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    h, _ = signup(c)
    a = up(c, h, "x.txt", b"first revision of the file")["source"]
    assert up(c, h, "y.txt", b"first revision of the file")["status"] == "duplicate"
    b = up(c, h, "x.txt", b"second revision of the file")["source"]
    assert (a["version"], b["version"]) == (1, 2)
    with eng.connect() as conn:
        assert conn.execute(text("select count(*) from documents")).scalar() == 2
        assert conn.execute(text("select count(*) from documents where is_current")).scalar() == 1
        assert conn.execute(text("select version_num from alembic_version")).scalar() == "0004"


# ------------------------------------------------------------------------------------------- tenant settings, pagination everywhere
def test_tenant_settings_validation_and_isolation(app_pair):
    c, _ = app_pair
    admin, _ = signup(c)
    mgr, _ = add_user(c, admin, "m@x.io", "manager")
    assert c.get("/admin/tenant-settings", headers=mgr).status_code == 403
    default = c.get("/admin/tenant-settings", headers=admin).json()
    assert default["retention_days_documents"] is None and default["web_allowed"] is True and default["web_allowed_domains"] == []
    body = {"retention_days_documents": 90, "retention_days_audit": 365, "web_allowed_domains": ["Example.com", " .docs.python.org "], "redact_stored_messages": True}
    assert c.put("/admin/tenant-settings", json=body, headers=admin).json()["web_allowed_domains"] == ["example.com", "docs.python.org"]
    got = c.get("/admin/tenant-settings", headers=admin).json()
    assert got["retention_days_documents"] == 90 and got["redact_stored_messages"] is True
    for bad in ({"retention_days_audit": 7}, {"retention_days_documents": 0}, {"web_allowed_domains": ["not a domain"]}, {"web_allowed_domains": ["localhost"]}, {"web_allowed_domains": ["http://x.com"]}):
        assert c.put("/admin/tenant-settings", json=bad, headers=admin).status_code == 422, bad
    other, _ = signup(c, "Other Co", "o@o.io")
    assert c.get("/admin/tenant-settings", headers=other).json()["retention_days_documents"] is None  # per tenant


def test_pagination_on_admin_jobs_conversations(app_pair):
    c, _ = app_pair
    admin, _ = signup(c)
    for i in range(3):
        add_user(c, admin, f"u{i}@x.io", "user")
    r = c.get("/admin/users?limit=2", headers=admin)
    assert len(r.json()) == 2 and r.headers["x-total-count"] == "4"
    r = c.get("/admin/audit?limit=3&offset=1", headers=admin)
    assert len(r.json()) == 3 and int(r.headers["x-total-count"]) >= 7
    assert all(e["outcome"] == "success" for e in c.get("/admin/audit?outcome=success&limit=50", headers=admin).json())
    for i in range(3):
        c.post("/conversations", headers={**admin, **H})
    r = c.get("/conversations?limit=2", headers={**admin, **H})
    assert len(r.json()) == 2 and r.headers["x-total-count"] == "3"
    assert c.get("/jobs?limit=5", headers={**admin, **H}).headers["x-total-count"] == "0"
