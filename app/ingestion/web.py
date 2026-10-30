"""Safe public-URL ingestion: scheme/host validation, SSRF guard, size/time limits, readable-text extraction."""
from __future__ import annotations

import ipaddress
import socket
import ssl
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..core import Extracted, IngestError, Unit

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "td", "th", "dd", "dt", "figcaption"]
DROP_TAGS = ["script", "style", "noscript", "nav", "footer", "aside", "form", "header", "svg", "iframe"]


def resolve_public(url: str, allow_private: bool = False) -> tuple[str, list[str]]:
    """Validate scheme/host and resolve ONCE. -> (url without fragment, vetted IP addresses to connect to)."""
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
    ips: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not allow_private and not ip.is_global:
            raise IngestError("URL points to a private, local or otherwise non-public network address and was blocked")
        if str(ip) not in ips:
            ips.append(str(ip))
    return urldefrag(url.strip())[0], ips


def validate_url(url: str, allow_private: bool = False) -> str:
    return resolve_public(url, allow_private)[0]


def _pin(url: str, ip: str) -> tuple[str, dict]:
    """Rewrite the URL to the vetted IP (no second DNS lookup => no DNS-rebinding window) keeping Host/SNI of the original name."""
    p = urlsplit(url)
    host_hdr = p.hostname if p.port is None else f"{p.hostname}:{p.port}"
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = ip_host if p.port is None else f"{ip_host}:{p.port}"
    ext = {"sni_hostname": p.hostname} if p.scheme == "https" else {}
    return p._replace(netloc=netloc).geturl(), {"headers": {"Host": host_hdr}, "extensions": ext}


def fetch(url: str, s: Settings, transport: Optional[httpx.BaseTransport] = None) -> tuple[str, str, str]:
    """-> (final_url, content_type, body). Every hop is validated, resolved once and connected by IP."""
    max_bytes = s.url_max_mb * 1024 * 1024
    current, ips = resolve_public(url, s.allow_private_urls)
    base_headers = {"User-Agent": "MultiAgentKnowledgeAssistant/2.0", "Accept": "text/html,text/plain;q=0.9"}
    verify = ssl.create_default_context(cafile=s.url_ca_bundle) if s.url_ca_bundle else True
    with httpx.Client(follow_redirects=False, timeout=s.url_timeout, transport=transport, headers=base_headers, verify=verify) as client:
        for _ in range(s.url_max_redirects + 1):
            last_err: Optional[Exception] = None
            for ip in ips[:3]:
                target, kw = (current, {}) if transport is not None else _pin(current, ip)
                try:
                    with client.stream("GET", target, **kw) as r:
                        if r.is_redirect:
                            loc = r.headers.get("location")
                            if not loc:
                                raise IngestError("Redirect without a Location header")
                            current, ips = resolve_public(urljoin(current, loc), s.allow_private_urls)
                            break
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
                        return current, ctype or "text/html", bytes(body).decode(r.encoding or "utf-8", errors="replace")
                except httpx.TimeoutException as e:
                    raise IngestError("Timed out fetching the URL") from e
                except httpx.ConnectError as e:
                    last_err = e  # try the next vetted address
                    continue
                except httpx.HTTPError as e:
                    raise IngestError(f"Could not fetch the URL: {e}") from e
            else:
                raise IngestError(f"Could not connect to the URL: {last_err}")
    raise IngestError("Too many redirects")


def extract_html(final_url: str, ctype: str, body: str, as_file: bool = False) -> Extracted:
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
        tables_out = []
        for ti, tb in enumerate(soup.find_all("table"), 1):
            rows = [[" ".join(c.get_text(" ", strip=True).split()) for c in tr.find_all(["th", "td"])] for tr in tb.find_all("tr")]
            rows = [r for r in rows if any(r)]
            if len(rows) >= 2:
                tables_out.append({"location": {"table": ti} if as_file else {"url": final_url, "table": ti}, "header": rows[0], "rows": rows[1:]})
        units, section = [], None
        for el in soup.find_all(BLOCK_TAGS):
            if el.find(BLOCK_TAGS):  # only leaf blocks, avoids duplicated text
                continue
            text = " ".join(el.get_text(" ", strip=True).split())
            if not text:
                continue
            if el.name.startswith("h") and len(el.name) == 2:
                section = text
            if as_file:  # uploaded .html file: cite by paragraph number + section instead of a URL
                loc = {"paragraph": len(units) + 1}
            else:
                loc = {"url": final_url}
            if section and not el.name.startswith("h"):
                loc["section"] = section
            units.append(Unit(text, loc))
    if not units:
        raise IngestError("No readable content found at the URL")
    ex = Extracted(units, title=title, tables=tables_out if ctype != "text/plain" else [])
    ex.meta["canonical_link"] = canon.get("href") if (ctype != "text/plain" and canon) else None
    return ex
