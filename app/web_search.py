"""Optional public-web search providers (SearXNG self-hosted, Brave). Results are only candidate URLs/snippets; page bodies are
fetched through the SSRF-guarded fetcher and treated as untrusted data."""
from __future__ import annotations

from typing import Optional

import httpx

from .config import Settings
from .core import ProviderError


def search(s: Settings, query: str, n: int = 5, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    p = s.web_search_provider.lower()
    if p == "none":
        raise ProviderError("Web search is not configured (set MKA_WEB_SEARCH_PROVIDER to searxng or brave)")
    try:
        with httpx.Client(timeout=s.url_timeout, transport=transport) as c:
            if p == "searxng":
                if not s.web_search_url:
                    raise ProviderError("MKA_WEB_SEARCH_URL is required for searxng")
                r = c.get(s.web_search_url.rstrip("/") + "/search", params={"q": query, "format": "json"})
                r.raise_for_status()
                return [{"title": x.get("title", ""), "url": x["url"], "snippet": x.get("content", "")} for x in r.json().get("results", [])[:n] if x.get("url")]
            if p == "brave":
                key = s.secret("brave_api_key")
                if not key:
                    raise ProviderError("BRAVE_API_KEY is not set")
                r = c.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n}, headers={"X-Subscription-Token": key, "Accept": "application/json"})
                r.raise_for_status()
                return [{"title": x.get("title", ""), "url": x["url"], "snippet": x.get("description", "")} for x in r.json().get("web", {}).get("results", [])[:n] if x.get("url")]
    except httpx.HTTPError as e:
        raise ProviderError(f"Web search failed: {e}") from e
    raise ProviderError(f"Unknown web search provider '{s.web_search_provider}'")
