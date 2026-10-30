"""Per-tenant policy lookups shared by the API and the agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .db import Database, TenantSettings


@dataclass
class WebPolicy:
    allowed: bool = True
    domains: list[str] = field(default_factory=list)  # empty = any public domain

    def permits(self, url: str) -> bool:
        if not self.allowed:
            return False
        if not self.domains:
            return True
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self.domains)


def web_policy(db: Database, tenant_id: str) -> WebPolicy:
    """Read-only: a tenant without a settings row gets the default (web allowed, any public domain)."""
    with db.session() as s:
        row = s.get(TenantSettings, tenant_id)
        return WebPolicy(bool(row.web_allowed), [d.lower() for d in (row.web_allowed_domains or [])]) if row else WebPolicy()
