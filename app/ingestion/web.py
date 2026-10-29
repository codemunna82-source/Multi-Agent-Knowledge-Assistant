"""Safe public-URL ingestion: scheme/host validation, SSRF guard, size/time limits, readable-text extraction."""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..core import Extracted, IngestError, Unit

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "td", "th", "dd", "dt", "figcaption"]
DROP_TAGS = ["script", "style", "noscript", "nav", "footer", "aside", "form", "header", "svg", "iframe"]


def validate_url(url: str, allow_private: bool = False) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError as e:
        raise IngestError(f"Invalid URL: {e}") from e
    if parts.scheme not in ("http", "https"):
        raise IngestError("Only http:// and https:// URLs are supported")
    if not parts.hostname:
        raise IngestError("Invalid URL: missing host")
    if parts.username or parts.password:
        raise IngestError("URLs with embedded credentials are not allowed")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, ValueError) as e:
        raise IngestError(f"Could not resolve host '{parts.hostname}'") from e
    if not allow_private:
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if not ip.is_global:
                raise IngestError("URL points to a private, local or otherwise non-public network address and was blocked")
    return urldefrag(url.strip())[0]


def fetch(url: str, s: Settings, transport: Optional[httpx.BaseTransport] = None) -> tuple[str, str, str]:
    """-> (final_url, content_type, body). Re-validates every redirect hop."""
    max_bytes = s.url_max_mb * 1024 * 1024
    current = validate_url(url, s.allow_private_urls)
    headers = {"User-Agent": "MultiAgentKnowledgeAssistant/1.0", "Accept": "text/html,text/plain;q=0.9"}
    with httpx.Client(follow_redirects=False, timeout=s.url_timeout, transport=transport, headers=headers) as client:
        for _ in range(s.url_max_redirects + 1):
            try:
                with client.stream("GET", current) as r:
                    if r.is_redirect:
                        loc = r.headers.get("location")
                        if not loc:
                            raise IngestError("Redirect without a Location header")
                        current = validate_url(urljoin(current, loc), s.allow_private_urls)
                        continue
                    if r.status_code >= 400:
                        raise IngestError(f"The URL returned HTTP {r.status_code}")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in ("text/html", "application/xhtml+xml", "text/plain", ""):
                        raise IngestError(f"Unsupported content type '{ctype}' (only HTML and plain text pages)")
                    body = bytearray()
                    for part in r.iter_bytes():
                        body += part
                        if len(body) > max_bytes:
                            raise IngestError(f"The page exceeds the {s.url_max_mb} MB limit")
                    enc = r.encoding or "utf-8"
                    return current, ctype or "text/html", bytes(body).decode(enc, errors="replace")
            except httpx.TimeoutException as e:
                raise IngestError("Timed out fetching the URL") from e
            except httpx.HTTPError as e:
                raise IngestError(f"Could not fetch the URL: {e}") from e
    raise IngestError("Too many redirects")


def extract_html(final_url: str, ctype: str, body: str) -> Extracted:
    if ctype == "text/plain":
        blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
        units = [Unit(b, {"url": final_url}) for b in blocks]
        title = None
    else:
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        canon = soup.find("link", rel="canonical")
        for t in soup(DROP_TAGS):
            t.decompose()
        units, section = [], None
        for el in soup.find_all(BLOCK_TAGS):
            if el.find(BLOCK_TAGS):  # only leaf blocks, avoids duplicated text
                continue
            text = " ".join(el.get_text(" ", strip=True).split())
            if not text:
                continue
            if el.name.startswith("h") and len(el.name) == 2:
                section = text
            loc = {"url": final_url}
            if section and not el.name.startswith("h"):
                loc["section"] = section
            units.append(Unit(text, loc))
    if not units:
        raise IngestError("No readable content found at the URL")
    ex = Extracted(units, title=title)
    ex.meta["canonical_link"] = canon.get("href") if (ctype != "text/plain" and canon) else None
    return ex
