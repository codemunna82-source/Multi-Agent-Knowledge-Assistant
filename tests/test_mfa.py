import base64
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.security import totp

PW = "correct horse battery"
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def test_rfc6238_test_vectors_and_window_and_replay():
    for t, exp in [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]:
        assert totp.totp(RFC_SECRET, t, 8) == exp
    now = 1_700_000_000
    code = totp.totp(RFC_SECRET, now)
    c = totp.verify(RFC_SECRET, code, 0, at=now)
    assert c == now // 30
    assert totp.verify(RFC_SECRET, code, c, at=now) is None                        # replay of the same step is refused
    assert totp.verify(RFC_SECRET, totp.totp(RFC_SECRET, now - 30), 0, at=now) is not None   # one step of clock drift is fine
    assert totp.verify(RFC_SECRET, totp.totp(RFC_SECRET, now - 120), 0, at=now) is None       # four steps is not
    assert totp.verify(RFC_SECRET, "abcdef", 0, at=now) is None and totp.verify(RFC_SECRET, "12345", 0, at=now) is None


def test_recovery_codes_are_single_use():
    codes = totp.new_recovery_codes(3)
    hashes = [totp.hash_code(c) for c in codes]
    left = totp.use_recovery(hashes, codes[1].upper())
    assert left is not None and len(left) == 2 and totp.use_recovery(left, codes[1]) is None


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", _env_file=None)
    c = TestClient(create_app(s))
    r = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    return c, {"Authorization": "Bearer " + r["access_token"]}


def _enable(c, h):
    sec = c.post("/auth/mfa/setup", headers=h).json()
    assert sec["otpauth_uri"].startswith("otpauth://totp/") and sec["secret"] in sec["otpauth_uri"]
    assert c.get("/auth/mfa", headers=h).json()["enabled"] is False                         # not active until proven
    bad = c.post("/auth/mfa/enable", json={"code": "000000"}, headers=h)
    assert bad.status_code == 422
    en = c.post("/auth/mfa/enable", json={"code": totp.totp(sec["secret"])}, headers=h).json()
    assert en["enabled"] and len(en["recovery_codes"]) == 10
    return sec["secret"], en["recovery_codes"]


def test_login_requires_second_factor_once_enabled(env):
    c, h = env
    secret, recovery = _enable(c, h)
    r = c.post("/auth/login", json={"email": "a@acme.io", "password": PW})
    assert r.status_code == 401 and r.headers["x-mfa-required"] == "true"
    assert c.post("/auth/login", json={"email": "a@acme.io", "password": "wrong password!!"}).headers.get("x-mfa-required") is None    # no MFA hint without the password
    assert c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": "123456"}).status_code == 401
    # the code used to enable MFA cannot be replayed to log in; wait for the next step by crafting the neighbouring one
    nxt = totp.totp(secret, time.time() + 30)
    ok = c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": nxt})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": nxt}).status_code == 401      # replay
    rc = c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": recovery[0]})
    assert rc.status_code == 200
    assert c.post("/auth/login", json={"email": "a@acme.io", "password": PW, "otp": recovery[0]}).status_code == 401  # spent
    assert c.get("/auth/mfa", headers=h).json() == {"enabled": True, "recovery_codes_left": 9}


def test_disable_needs_password_and_code(env):
    c, h = env
    secret, recovery = _enable(c, h)
    assert c.post("/auth/mfa/setup", headers=h).status_code == 409
    assert c.post("/auth/mfa/disable", json={"password": "nope nope nope", "code": recovery[0]}, headers=h).status_code == 401
    assert c.post("/auth/mfa/disable", json={"password": PW, "code": "000000"}, headers=h).status_code == 401
    assert c.post("/auth/mfa/disable", json={"password": PW, "code": recovery[1]}, headers=h).json() == {"enabled": False}
    assert c.post("/auth/login", json={"email": "a@acme.io", "password": PW}).status_code == 200
    actions = [a["action"] for a in c.get("/admin/audit?limit=50", headers=h).json()] if c.get("/admin/audit?limit=50", headers=h).status_code == 200 else []
    assert not actions or {"mfa_enabled", "mfa_disabled"} <= set(actions)


def test_mfa_endpoints_need_authentication(env):
    c, _ = env
    for m, p in [("get", "/auth/mfa"), ("post", "/auth/mfa/setup"), ("post", "/auth/mfa/enable"), ("post", "/auth/mfa/disable")]:
        assert getattr(c, m)(p, **({} if m == "get" else {"json": {"code": "1", "password": "x"}})).status_code == 401
