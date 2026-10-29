import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.core import IngestError
from app.ingestion import web
from app.service import Knowledge

from .conftest import ask

PAGE = b"<html><head><title>Hello Page</title></head><body><nav>menu</nav><h1>Intro</h1><p>The widget warranty lasts 24 months.</p><script>evil()</script></body></html>"


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)

    def handler(req: httpx.Request):
        if req.url.path == "/redirect-private":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        if req.url.path == "/pdf":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=PAGE)

    import socket

    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        table = {"example.com": "93.184.216.34", "evil.test": "93.184.216.35"}
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(web.socket, "getaddrinfo", fake)
    k = Knowledge(s, url_transport=httpx.MockTransport(handler))
    return TestClient(create_app(s, k))


def test_url_ingest_and_cite(web_client):
    r = web_client.post("/sources/url", json={"url": "https://example.com/page#frag"}).json()
    assert r["status"] == "ready" and r["source"]["title"] == "Hello Page" and r["source"]["final_url"] == "https://example.com/page"
    a = ask(web_client, "How long is the widget warranty?", session="default")
    assert "24 months" in a["answer"] and a["citations"][0]["source"].startswith("https://example.com/page")
    assert "evil()" not in str(a) and "menu" not in str(a)


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/", "http://[::1]/", "ftp://example.com/a", "file:///etc/passwd", "https://user:pw@example.com/", "not a url", "https://example.com/redirect-private", "https://example.com/pdf"])
def test_blocked_or_invalid_urls_rejected(web_client, url):
    r = web_client.post("/sources/url", json={"url": url}).json()
    assert r["status"] == "failed" and r["error"]
    assert web_client.get("/sources").json() == []


def test_validate_url_allows_private_only_when_configured():
    with pytest.raises(IngestError):
        web.validate_url("http://127.0.0.1/")
    assert web.validate_url("http://127.0.0.1/#x", allow_private=True) == "http://127.0.0.1/"


def test_api_errors(client):
    h = {"X-Session-ID": "s1"}
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/sources", headers={"X-Session-ID": "../etc"}).status_code == 400
    assert client.get("/sources/zzz", headers=h).status_code == 404
    assert client.post("/ask", json={"question": ""}, headers=h).status_code == 422
    assert client.post("/ask", json={"question": "hi", "source_ids": ["0" * 32]}, headers=h).status_code == 404
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert "no indexed sources" in client.post("/ask", json={"question": "anything?"}, headers=h).json()["answer"].lower()


def test_chroma_backend(tmp_path):
    pytest.importorskip("chromadb")
    s = Settings(data_dir=str(tmp_path / "d"), vector_store="chroma", _env_file=None)
    c = TestClient(create_app(s))
    from .conftest import make_pdf, upload

    sid = upload(c, "a.pdf", make_pdf(["Warranty lasts 24 months for all widgets."]))["source"]["id"]
    assert "24 months" in ask(c, "How long is the warranty?")["answer"]
    c.delete(f"/sources/{sid}", headers={"X-Session-ID": "s1"})
    assert ask(c, "How long is the warranty?")["verified"] is False


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Knowledge Assistant" in r.text and "frame-ancestors" in r.headers["content-security-policy"]
