import os
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


PW = "correct horse battery"


@pytest.fixture
def secure(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="1000/minute", rate_limit_ingest="1000/minute",
                 rate_limit_auth="1000/minute", _env_file=None)
    return TestClient(create_app(s)), s


def signup(c, tenant="Acme", email="admin@acme.io"):
    r = c.post("/auth/signup", json={"tenant_name": tenant, "email": email, "password": PW})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()["user"]


def add_user(c, admin_h, email, role):
    r = c.post("/admin/users", json={"email": email, "password": PW, "role": role}, headers=admin_h)
    assert r.status_code == 201, r.text
    t = c.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}, r.json()


def up(c, h, name, data, vis="tenant", ws="w1"):
    r = c.post("/sources/upload", files=[("files", (name, data))], data={"visibility": vis}, headers={**h, "X-Session-ID": ws})
    assert r.status_code == 200, r.text
    return r.json()[0]


def test_auth_required_and_login_flow(secure):
    c, _ = secure
    assert c.get("/sources").status_code == 401
    assert c.get("/sources", headers={"Authorization": "Bearer garbage"}).status_code == 401
    h, u = signup(c)
    assert u["role"] == "admin" and c.get("/auth/me", headers=h).json()["email"] == "admin@acme.io"
    assert c.post("/auth/login", json={"email": "admin@acme.io", "password": "wrong-password-1"}).status_code == 401
    assert c.post("/auth/login", json={"email": "nobody@acme.io", "password": PW}).status_code == 401
    assert c.post("/auth/signup", json={"tenant_name": "Xx", "email": "admin@acme.io", "password": PW}).status_code == 409
    assert c.post("/auth/signup", json={"tenant_name": "Xx", "email": "b@x.io", "password": "short"}).status_code == 422


def test_token_tamper_expiry_logout(secure):
    c, s = secure
    h, u = signup(c)
    forged = jwt.encode({"sub": u["id"], "tid": u["tenant_id"], "jti": "z", "exp": time.time() + 99}, "wrong-key-wrong-key-wrong-key-wrong", algorithm="HS256")
    assert c.get("/sources", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({"sub": u["id"], "tid": u["tenant_id"], "jti": "y", "exp": time.time() - 5}, s.jwt_key(), algorithm="HS256")
    r = c.get("/sources", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()
    none_alg = jwt.encode({"sub": u["id"], "tid": u["tenant_id"], "jti": "n", "exp": time.time() + 99}, "", algorithm="none")
    assert c.get("/sources", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401
    assert c.post("/auth/logout", headers=h).status_code == 200
    assert c.get("/sources", headers=h).status_code == 401  # revoked


def test_rbac_matrix(secure):
    c, _ = secure
    admin, _ = signup(c)
    viewer, _ = add_user(c, admin, "v@acme.io", "viewer")
    editor, _ = add_user(c, admin, "e@acme.io", "editor")
    r = c.post("/sources/upload", files=[("files", ("a.txt", b"hello world"))], headers=viewer)
    assert r.status_code == 403
    assert c.get("/sources", headers=viewer).status_code == 200
    assert c.post("/ask", json={"question": "hello"}, headers=viewer).status_code == 200
    assert c.get("/admin/users", headers=editor).status_code == 403
    assert c.get("/admin/audit", headers=editor).status_code == 403
    assert c.get("/admin/settings", headers=viewer).status_code == 403
    sid = up(c, editor, "doc.txt", b"editor document text")["source"]["id"]
    assert c.delete(f"/sources/{sid}", headers=viewer).status_code == 403
    other_editor, _ = add_user(c, admin, "e2@acme.io", "editor")
    assert c.delete(f"/sources/{sid}", headers={**other_editor, "X-Session-ID": "w1"}).status_code == 403  # not the owner
    assert c.delete(f"/sources/{sid}", headers={**admin, "X-Session-ID": "w1"}).status_code == 200  # admin may delete any


def test_role_change_applies_immediately_and_last_admin_protected(secure):
    c, _ = secure
    admin, au = signup(c)
    ed, eu = add_user(c, admin, "e@acme.io", "editor")
    assert c.get("/admin/users", headers=ed).status_code == 403
    assert c.patch(f"/admin/users/{eu['id']}", json={"role": "admin"}, headers=admin).status_code == 200
    assert c.get("/admin/users", headers=ed).status_code == 200  # same token, new role
    assert c.patch(f"/admin/users/{eu['id']}", json={"is_active": False}, headers=admin).status_code == 200
    assert c.get("/sources", headers=ed).status_code == 401  # disabled account
    assert c.patch(f"/admin/users/{au['id']}", json={"role": "viewer"}, headers=admin).status_code == 409
    assert c.delete(f"/admin/users/{au['id']}", headers=admin).status_code == 409


def test_tenant_isolation_everywhere(secure):
    c, s = secure
    a, _ = signup(c, "Tenant A", "a@a.io")
    b, _ = signup(c, "Tenant B", "b@b.io")
    src = up(c, a, "secret.txt", b"Project Zebra launches in May. Contact Priya Natarajan.")["source"]["id"]
    # same workspace id, different tenant
    assert c.get("/sources", headers={**b, "X-Session-ID": "w1"}).json() == []
    assert c.get(f"/sources/{src}", headers={**b, "X-Session-ID": "w1"}).status_code == 404
    assert c.delete(f"/sources/{src}", headers={**b, "X-Session-ID": "w1"}).status_code == 404
    r = c.post("/ask", json={"question": 'find "Zebra"'}, headers={**b, "X-Session-ID": "w1"}).json()
    assert r["details"].get("count", 0) == 0 and r["citations"] == []
    r = c.post("/ask", json={"question": "when does project zebra launch?", "source_ids": [src]}, headers={**b, "X-Session-ID": "w1"})
    assert r.status_code == 404
    # tenant A still fine
    assert c.post("/ask", json={"question": 'find "Zebra"'}, headers={**a, "X-Session-ID": "w1"}).json()["details"]["count"] == 1
    # conversations are private to their owner
    conv = c.post("/ask", json={"question": "hi"}, headers={**a, "X-Session-ID": "w1"}).json()["conversation_id"]
    assert c.get(f"/conversations/{conv}/messages", headers={**b, "X-Session-ID": "w1"}).status_code == 404
    assert c.get(f"/conversations/{conv}/messages", headers={**a, "X-Session-ID": "w1"}).status_code == 200
    # admin of B cannot see A's users/audit
    users_b = c.get("/admin/users", headers=b).json()
    assert [u["email"] for u in users_b] == ["b@b.io"]
    assert not any("a@a.io" in str(e) or src in str(e) for e in c.get("/admin/audit", headers=b).json())


def test_document_acl_private_sources(secure):
    c, _ = secure
    admin, _ = signup(c)
    e1, _ = add_user(c, admin, "e1@acme.io", "editor")
    e2, _ = add_user(c, admin, "e2@acme.io", "editor")
    priv = up(c, e1, "salary.txt", b"Anjali earns a secret amount", vis="private")["source"]["id"]
    pub = up(c, e1, "handbook.txt", b"Anjali is mentioned in the handbook too", vis="tenant")["source"]["id"]
    ids2 = [s["id"] for s in c.get("/sources", headers={**e2, "X-Session-ID": "w1"}).json()]
    assert ids2 == [pub]
    assert c.get(f"/sources/{priv}", headers={**e2, "X-Session-ID": "w1"}).status_code == 404
    r = c.post("/ask", json={"question": "Does Anjali appear?"}, headers={**e2, "X-Session-ID": "w1"}).json()
    assert r["details"]["count"] == 1 and all(x["source"] == "handbook.txt" for x in r["citations"])
    r = c.post("/ask", json={"question": "What does Anjali earn? secret amount"}, headers={**e2, "X-Session-ID": "w1"}).json()
    assert "salary.txt" not in str(r)
    for h in (e1, admin):
        assert priv in [s["id"] for s in c.get("/sources", headers={**h, "X-Session-ID": "w1"}).json()]
    assert c.post("/sources/upload", files=[("files", ("a.txt", b"x y z"))], data={"visibility": "bogus"}, headers=e1).status_code == 422


def test_audit_log_content_and_privacy(secure):
    c, _ = secure
    admin, _ = signup(c)
    up(c, admin, "a.txt", b"some content here")
    c.post("/ask", json={"question": "my very private question about salaries"}, headers={**admin, "X-Session-ID": "w1"})
    c.get("/sources", headers={"Authorization": "Bearer nope"})
    ev = c.get("/admin/audit", headers=admin).json()
    actions = {e["action"] for e in ev}
    assert {"signup", "ingest_file", "ask"} <= actions
    assert "private question" not in str(ev) and "salaries" not in str(ev)  # only hash + length are stored
    ask_ev = next(e for e in ev if e["action"] == "ask")
    assert ask_ev["detail"]["question"]["chars"] == len("my very private question about salaries")
    assert all(e["request_id"] for e in ev)


def test_data_deletion_purge(secure, tmp_path):
    c, s = secure
    admin, _ = signup(c)
    up(c, admin, "a.txt", b"alpha beta gamma")
    up(c, admin, "b.txt", b"delta epsilon zeta", ws="w2")
    c.post("/ask", json={"question": "alpha"}, headers={**admin, "X-Session-ID": "w1"})
    assert c.request("DELETE", "/admin/data", json={"confirm": "no"}, headers=admin).status_code == 422
    r = c.request("DELETE", "/admin/data", json={"confirm": "DELETE-ALL-TENANT-DATA"}, headers=admin)
    assert r.json() == {"purged": True, "sources_removed": 2}
    assert c.get("/sources", headers={**admin, "X-Session-ID": "w1"}).json() == []
    assert c.get("/conversations", headers={**admin, "X-Session-ID": "w1"}).json() == []
    assert not any((tmp_path / "d" / "tenants").rglob("units.jsonl"))


def test_rate_limit_memory(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), rate_limit_ask="3/minute", _env_file=None)
    c = TestClient(create_app(s))
    codes = [c.post("/ask", json={"question": "hi"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = c.post("/ask", json={"question": "hi"})
    assert int(r.headers["retry-after"]) >= 1


def test_login_is_rate_limited(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="y" * 40, rate_limit_auth="3/minute", _env_file=None)
    c = TestClient(create_app(s))
    codes = [c.post("/auth/login", json={"email": "a@b.io", "password": "x" * 12}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_production_config_validation(tmp_path):
    bad = Settings(data_dir=str(tmp_path), env="production", _env_file=None)
    with pytest.raises(RuntimeError) as e:
        create_app(bad)
    for needle in ("AUTH_ENABLED", "JWT_SECRET", "SIGNUP", "PostgreSQL"):
        assert needle in str(e.value)


def test_admin_settings_masks_secrets(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="s" * 40, openai_api_key="sk-supersecret", _env_file=None)
    c = TestClient(create_app(s))
    h, _ = signup(c)
    dump = str(c.get("/admin/settings", headers=h).json())
    assert "sk-supersecret" not in dump and "s" * 40 not in dump and "***set***" in dump


@pytest.mark.skipif(not os.environ.get("MKA_TEST_PG_URL"), reason="set MKA_TEST_PG_URL to run PostgreSQL integration tests")
def test_postgres_backend(tmp_path):
    from sqlalchemy import text

    from app.db import Base, Database

    url = os.environ["MKA_TEST_PG_URL"]
    db = Database(url)
    Base.metadata.drop_all(db.engine)
    db = Database(url)
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="p" * 40, database_url=url, _env_file=None)
    c = TestClient(create_app(s, db=db))
    h, _ = signup(c)
    assert up(c, h, "pg.txt", b"postgres stored identity and audit")["status"] == "ready"
    assert any(e["action"] == "ingest_file" for e in c.get("/admin/audit", headers=h).json())
    with db.engine.connect() as conn:
        assert conn.execute(text("select count(*) from users")).scalar() == 1


@pytest.mark.skipif(not os.environ.get("MKA_TEST_REDIS_URL"), reason="set MKA_TEST_REDIS_URL to run Redis integration tests")
def test_redis_rate_limit_shared_between_instances(tmp_path):
    import redis

    url = os.environ["MKA_TEST_REDIS_URL"]
    r = redis.Redis.from_url(url)
    r.flushdb()
    s = Settings(data_dir=str(tmp_path / "d"), rate_limit_ask="4/minute", redis_url=url, _env_file=None)
    c1, c2 = TestClient(create_app(s)), TestClient(create_app(s))  # two "replicas"
    codes = [cl.post("/ask", json={"question": "hi"}).status_code for cl in (c1, c2, c1, c2, c1, c2)]
    assert codes == [200, 200, 200, 200, 429, 429]
