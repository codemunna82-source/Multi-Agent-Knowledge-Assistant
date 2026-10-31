"""OIDC relying party tested against an in-process mock IdP (httpx.MockTransport + a throw-away RSA key). This proves OUR validation
(signature, iss/aud/exp/nonce, PKCE, state, account rules); it does not test any real identity provider."""
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.security import oidc

ISS = "https://idp.example.com/realms/acme"
CID = "mka-client"
REDIRECT = "http://testserver/auth/oidc/callback"
PW = "correct horse battery"


class IdP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "k1"
        self.claims: dict = {}
        self.sign_with = self.key
        self.token_status = 200
        self.seen_form: dict = {}
        self.alg = "RS256"

    def jwks(self):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}]}

    def id_token(self, nonce):
        now = int(time.time())
        claims = {"iss": ISS, "aud": CID, "sub": "u-123", "iat": now, "exp": now + 300, "nonce": nonce, "email": "sso@acme.io", "email_verified": True, **self.claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.sign_with, algorithm=self.alg, headers={"kid": self.kid})

    def handler(self, nonce_box):
        def h(req: httpx.Request):
            u = str(req.url)
            if u.endswith("/.well-known/openid-configuration"):
                return httpx.Response(200, json={"issuer": ISS, "authorization_endpoint": ISS + "/auth", "token_endpoint": ISS + "/token", "jwks_uri": ISS + "/jwks"})
            if u.endswith("/jwks"):
                return httpx.Response(200, json=self.jwks())
            if u.endswith("/token"):
                self.seen_form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
                if self.token_status != 200:
                    return httpx.Response(self.token_status, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"id_token": self.id_token(nonce_box["nonce"]), "access_token": "x", "token_type": "Bearer"})
            return httpx.Response(404)
        return h


@pytest.fixture
def sso(tmp_path, monkeypatch):
    idp, box = IdP(), {}
    monkeypatch.setattr(oidc, "_client", lambda timeout=10.0: httpx.Client(transport=httpx.MockTransport(idp.handler(box)), timeout=timeout))
    oidc._cache.clear()

    def build(**kw):
        s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", oidc_issuer=ISS, oidc_client_id=CID, oidc_redirect_uri=REDIRECT, _env_file=None, **kw)
        return TestClient(create_app(s), follow_redirects=False)

    def start(c):
        r = c.get("/auth/oidc/login")
        assert r.status_code == 302 and r.headers["location"].startswith(ISS + "/auth?")
        q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
        box["nonce"] = q["nonce"]
        return q

    return idp, build, start


def _signup(c, email="sso@acme.io"):
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": email, "password": PW}).json()
    return t["user"]["tenant_id"]


def test_login_redirect_carries_state_nonce_and_pkce_s256(sso):
    idp, build, start = sso
    q = start(build())
    assert q["response_type"] == "code" and q["client_id"] == CID and q["redirect_uri"] == REDIRECT and q["code_challenge_method"] == "S256" and len(q["state"]) >= 24
    assert q["code_challenge"] != q["nonce"] and "openid" in q["scope"]


def test_not_configured_is_404_and_config_reports_disabled(tmp_path):
    c = TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, _env_file=None)), follow_redirects=False)
    assert c.get("/auth/oidc/config").json() == {"enabled": False, "login_url": None}
    assert c.get("/auth/oidc/login").status_code == 404 and c.get("/auth/oidc/callback?code=a&state=b").status_code == 404


def test_existing_account_is_linked_by_verified_email_and_gets_a_session(sso):
    idp, build, start = sso
    c = build(allow_signup=True)
    _signup(c)
    q = start(c)
    r = c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]})
    assert r.status_code == 302 and r.headers["location"] == "/" and "mka_refresh" in r.headers.get("set-cookie", "")
    assert idp.seen_form["grant_type"] == "authorization_code" and idp.seen_form["code_verifier"] and idp.seen_form["code"] == "abc"
    tok = c.post("/auth/refresh").json()                       # the cookie from the SSO login is a real session
    assert tok["user"]["email"] == "sso@acme.io"
    q = start(c)                                               # second login goes through the stored (issuer, sub) link
    idp.claims = {"email": "changed@acme.io"}
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 302


def test_unknown_user_is_refused_unless_auto_provisioned_and_never_becomes_admin(sso):
    idp, build, start = sso
    c = build()
    q = start(c)
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 403
    c2 = build(oidc_auto_provision=True, oidc_tenant_id="nope")
    q = start(c2)
    assert c2.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 403          # tenant must exist
    c3 = build(allow_signup=True)
    tid = _signup(c3, "boss@acme.io")
    c4 = build(oidc_auto_provision=True, oidc_tenant_id=tid, oidc_default_role="admin")
    q = start(c4)
    assert c4.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 302
    assert c4.post("/auth/refresh").json()["user"]["role"] == "user"                                                # 'admin' in config is ignored


@pytest.mark.parametrize("claims,why", [
    ({"nonce": "wrong"}, "nonce"), ({"aud": "someone-else"}, "aud"), ({"iss": "https://evil.example"}, "iss"), ({"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}, "exp"),
    ({"email_verified": False}, "verified"), ({"email": None}, "email"),
])
def test_bad_id_tokens_are_rejected(sso, claims, why):
    idp, build, start = sso
    c = build(oidc_auto_provision=False)
    _signup(c)
    c.cookies.clear()                                           # drop the signup session so only the SSO attempt could create one
    q = start(c)
    idp.claims = claims
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code in (401, 403), why
    assert "mka_refresh" not in c.cookies


def test_forged_signature_state_mismatch_replayed_cookie_and_idp_errors(sso):
    idp, build, start = sso
    c = build()
    _signup(c)
    q = start(c)
    idp.sign_with = idp.other                                   # token signed by a key that is not in the JWKS
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 401
    idp.sign_with = idp.key
    q = start(c)
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": "attacker-chosen"}).status_code == 401      # CSRF: state must match the cookie
    assert build().get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 401       # no cookie = no login
    q = start(c)
    idp.token_status = 400
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 401
    assert c.get("/auth/oidc/callback", params={"error": "access_denied"}).status_code == 400


def test_hs256_and_none_tokens_are_not_accepted(sso):
    idp, build, start = sso
    s = Settings(oidc_issuer=ISS, oidc_client_id=CID, oidc_redirect_uri=REDIRECT, _env_file=None)
    now = int(time.time())
    body = {"iss": ISS, "aud": CID, "sub": "x", "iat": now, "exp": now + 60, "nonce": "n"}
    for tok in (jwt.encode(body, "secret" * 8, algorithm="HS256", headers={"kid": "k1"}), jwt.encode(body, None, algorithm="none", headers={"kid": "k1"})):
        with pytest.raises(oidc.OidcError):
            oidc.validate_id_token(s, tok, "n")


def test_domain_allow_list_and_disabled_users(sso):
    idp, build, start = sso
    c = build(oidc_allowed_domains="other.io")
    _signup(c)
    q = start(c)
    assert c.get("/auth/oidc/callback", params={"code": "abc", "state": q["state"]}).status_code == 403
