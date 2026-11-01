"""Ship audit events to a SIEM / log collector (HTTP). At-least-once: the cursor moves only after the collector answered 2xx.
Events contain ids, actions, outcomes and IPs - never question or document text (see security/audit.py)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy import select

from .db import AuditEvent

log = logging.getLogger("mka.siem")
MAX_BATCHES = 20


def _cursor_file(k) -> Path:
    p = Path(k.settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "siem_cursor.json"


def _read_cursor(k) -> int:
    try:
        return int(json.loads(_cursor_file(k).read_text())["last_id"])
    except (OSError, ValueError, KeyError):
        return 0


def event_dict(r: AuditEvent) -> dict:
    return {"id": r.id, "ts": r.ts.isoformat(), "tenant_id": r.tenant_id, "user_id": r.user_id, "action": r.action, "resource": r.resource, "outcome": r.outcome, "ip": r.ip,
            "request_id": r.request_id, "detail": r.detail}


def _body(k, events: list[dict]) -> tuple[str, dict]:
    s = k.settings
    token = s.secret("siem_token")
    if s.siem_format == "splunk_hec":
        lines = [json.dumps({"time": datetime_epoch(e["ts"]), "sourcetype": "mka:audit", "event": e}, ensure_ascii=False) for e in events]
        return "\n".join(lines), ({"Authorization": f"Splunk {token}"} if token else {})
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", ({"Authorization": f"Bearer {token}"} if token else {})


def datetime_epoch(ts: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(ts).timestamp()


def ship(k, dry_run: bool = False) -> dict:
    s = k.settings
    if not s.siem_url:
        return {"removed": 0, "skipped": "MKA_SIEM_URL is not set"}
    last, sent = _read_cursor(k), 0
    for _ in range(MAX_BATCHES):
        with k.db.session() as db:
            rows = db.scalars(select(AuditEvent).where(AuditEvent.id > last).order_by(AuditEvent.id).limit(s.siem_batch)).all()
            events = [event_dict(r) for r in rows]
        if not events:
            break
        if dry_run:
            return {"removed": 0, "pending_from_id": last, "would_send_at_least": len(events)}
        body, headers = _body(k, events)
        try:
            with httpx.Client(timeout=s.url_timeout, transport=k.url_transport, follow_redirects=False) as c:
                r = c.post(s.siem_url, content=body.encode(), headers={"Content-Type": "application/x-ndjson", "User-Agent": "mka-siem/3.1", **headers})
        except httpx.HTTPError as e:
            return {"removed": 0, "sent": sent, "error": f"collector unreachable: {str(e)[:100]}", "cursor": last}
        if r.status_code >= 300:
            return {"removed": 0, "sent": sent, "error": f"collector answered HTTP {r.status_code}", "cursor": last}
        last = events[-1]["id"]
        _cursor_file(k).write_text(json.dumps({"last_id": last}))
        sent += len(events)
    return {"removed": 0, "sent": sent, "cursor": last}
