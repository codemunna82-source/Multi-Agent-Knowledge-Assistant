"""Append-only audit trail. Never stores document text or raw questions (hash + length only)."""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ..db import AuditEvent, Database

log = logging.getLogger("mka.audit")


def digest(text: str) -> dict:
    return {"sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "chars": len(text)}


class Auditor:
    def __init__(self, db: Database, enabled: bool = True):
        self.db, self.enabled = db, enabled

    def record(self, action: str, *, tenant_id: Optional[str] = None, user_id: Optional[str] = None, resource: Optional[str] = None,
               outcome: str = "success", ip: Optional[str] = None, request_id: Optional[str] = None, detail: Optional[dict] = None) -> None:
        if not self.enabled:
            return
        try:
            with self.db.session() as s:
                s.add(AuditEvent(action=action, tenant_id=tenant_id, user_id=user_id, resource=(resource or "")[:300] or None,
                                 outcome=outcome, ip=ip, request_id=request_id, detail=detail))
        except Exception:  # auditing must never take the request down, but the failure must be visible
            log.exception("failed to write audit event %s", action)
