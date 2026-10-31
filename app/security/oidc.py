"""OpenID Connect relying party: authorization-code flow with PKCE (S256), state + nonce, ID-token validation against the IdP's JWKS.

Security properties enforced here (all covered by tests/test_oidc.py with a mock IdP):
 - the transaction (state, nonce, PKCE verifier) lives in a short-lived signed httpOnly cookie, bound to the browser that started the login
 - ID token: signature via the IdP's JWKS, algorithm allow-list (RS256/ES256 - never `none`/HS*), `iss`, `aud`, `exp`, `nonce` checked
 - the discovery document's `issuer` must equal the configured issuer
 - accounts are matched by (issuer, subject); linking to an existing local account by e-mail happens only when the IdP says `email_verified`
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt

from ..config import Settings

ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384"]
TX_COOKIE = "mka_oidc"
TX_TTL = 600


class OidcError(Exception):
    pass


def _client(timeout: float = 10.0) -> httpx.Client:
    """Factory for the IdP calls (tests replace it with a client on httpx.MockTransport)."""
    return httpx.Client(timeout=timeout, follow_redirects=False)


def enabled(s: Settings) -> bool:
    return bool(s.oidc_issuer and s.oidc_client_id and s.oidc_redirect_uri)


_cache: dict[str, tuple[float, dict]] = {}


def _get_json(url: str, ttl: float = 300.0, fresh: bool = False) -> dict:
    hit = _cache.get(url)
    if hit and not fresh and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        with _client() as c:
            r = c.get(url)
        if r.status_code != 200:
            raise OidcError(f"Identity provider answered HTTP {r.status_code} for {url}")
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OidcError(f"Identity provider unreachable: {e}") from e
    _cache[url] = (time.time(), data)
    return data


def discovery(s: Settings) -> dict:
    issuer = s.oidc_issuer.rstrip("/")
    d = _get_json(issuer + "/.well-known/openid-configuration")
    if d.get("issuer", "").rstrip("/") != issuer:
        raise OidcError("Discovery document issuer does not match the configured issuer")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not d.get(k):
            raise OidcError(f"Discovery document has no {k}")
    return d


def new_transaction() -> dict:
    verifier = secrets.token_urlsafe(64)
    return {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24), "verifier": verifier}


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorization_url(s: Settings, tx: dict) -> str:
    q = {"response_type": "code", "client_id": s.oidc_client_id, "redirect_uri": s.oidc_redirect_uri, "scope": s.oidc_scopes, "state": tx["state"], "nonce": tx["nonce"],
         "code_challenge": challenge(tx["verifier"]), "code_challenge_method": "S256"}
    return discovery(s)["authorization_endpoint"] + ("&" if "?" in discovery(s)["authorization_endpoint"] else "?") + urlencode(q)


def seal(s: Settings, tx: dict) -> str:
    return jwt.encode({**tx, "exp": int(time.time()) + TX_TTL, "typ": "oidc-tx"}, s.jwt_key(), algorithm="HS256")


def unseal(s: Settings, cookie: Optional[str]) -> dict:
    if not cookie:
        raise OidcError("Login session missing or expired - start again")
    try:
        tx = jwt.decode(cookie, s.jwt_key(), algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError as e:
        raise OidcError("Login session missing or expired - start again") from e
    if tx.get("typ") != "oidc-tx":
        raise OidcError("Invalid login session")
    return tx


def exchange_code(s: Settings, code: str, verifier: str) -> dict:
    d = discovery(s)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": s.oidc_redirect_uri, "client_id": s.oidc_client_id, "code_verifier": verifier}
    secret = s.secret("oidc_client_secret")
    if secret:
        form["client_secret"] = secret
    try:
        with _client() as c:
            r = c.post(d["token_endpoint"], data=form, headers={"Accept": "application/json"})
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OidcError(f"Token exchange failed: {e}") from e
    if r.status_code != 200 or "id_token" not in body:
        raise OidcError(f"Token endpoint refused the code ({body.get('error', r.status_code)})")
    return body


def _signing_key(s: Settings, id_token: str):
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") not in ALGS:
        raise OidcError(f"ID token algorithm {header.get('alg')!r} is not accepted")
    uri = discovery(s)["jwks_uri"]
    for fresh in (False, True):  # the IdP may have rotated keys: refetch once before giving up
        jwks = _get_json(uri, fresh=fresh)
        for k in jwks.get("keys", []):
            if k.get("kid") == header.get("kid") or (not header.get("kid") and len(jwks.get("keys", [])) == 1):
                return jwt.PyJWK(k).key
    raise OidcError("ID token is signed with an unknown key")


def validate_id_token(s: Settings, id_token: str, nonce: str) -> dict:
    key = _signing_key(s, id_token)
    try:
        claims = jwt.decode(id_token, key, algorithms=ALGS, audience=s.oidc_client_id, issuer=[s.oidc_issuer.rstrip("/"), s.oidc_issuer.rstrip("/") + "/"],
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=30)
    except jwt.PyJWTError as e:
        raise OidcError(f"ID token rejected: {e}") from e
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("ID token nonce mismatch")
    aud = claims["aud"]
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != s.oidc_client_id:
        raise OidcError("ID token authorised party mismatch")
    return claims


def domain_allowed(s: Settings, email: str) -> bool:
    allowed = [d.strip().lower() for d in s.oidc_allowed_domains.split(",") if d.strip()]
    return not allowed or email.rsplit("@", 1)[-1].lower() in allowed
