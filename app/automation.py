"""Automation: saved-search alerts, scheduled reports, webhook delivery and connector sync (folder / URL list / S3).

Webhook targets are validated like any URL the platform fetches (public addresses only, no redirects), payloads carry identifiers and counts - never document text."""
from __future__ import annotations

import json
import logging
import re
import shutil
import smtplib
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from .core import IngestError
from .db import Alert, Connector, ReportSchedule, SavedSearch, User
from .ingestion import web
from .ingestion.loaders import SUPPORTED as EXT_KIND
from .security.auth import Principal
from .storage import Scope
from .tools.exact import exact_search

log = logging.getLogger("mka.automation")
MAX_SYNC_FILES = 500


# ----------------------------------------------------------------------------- notifications (webhook / Slack / e-mail)
_EMAIL = re.compile(r"^[^@\s<>,;]{1,64}@[^@\s<>,;]{1,255}\.[A-Za-z]{2,}$")
_SLACK_HOSTS = ("hooks.slack.com", "hooks.slack-gov.com")


def _summary(payload: dict) -> tuple[str, str]:
    """-> (subject, body) in plain words. Built only from the identifiers/counts already in the payload - never document text."""
    ev = payload.get("event", "event")
    if ev == "saved_search_match":
        locs = ", ".join(str(x) for x in (payload.get("locations") or [])[:5])
        return (f"New match for \"{payload.get('term')}\" in {payload.get('document')}",
                f"\"{payload.get('term')}\" appears {payload.get('occurrences')} time(s) in {payload.get('document')}" + (f" ({locs})." if locs else "."))
    if ev == "report_ready":
        return (f"Report ready: {payload.get('title')}", f"The scheduled report \"{payload.get('schedule')}\" ({payload.get('format')}, {payload.get('size_bytes')} bytes) is ready: {payload.get('download_path')}")
    return (str(ev), json.dumps(payload, ensure_ascii=False)[:500])


def _send_mail(k, to: str, subject: str, body: str) -> str:
    s = k.settings
    if not s.smtp_host:
        return "failed: SMTP is not configured (MKA_SMTP_HOST)"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject.replace("\n", " ")[:200]
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.url_timeout) as c:
            if s.smtp_starttls:
                c.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                c.login(s.smtp_user, s.secret("smtp_password") or "")
            c.send_message(msg)
        return "sent"
    except (OSError, smtplib.SMTPException) as e:
        return f"failed: {str(e)[:120]}"


def notify(k, url: Optional[str], payload: dict) -> str:
    """-> "sent" | "skipped" | an error string. Never raises: a broken target must not break ingestion or the scheduler.
    `url` is an https webhook (Slack incoming-webhook URLs get Slack's {"text": ...} format) or `mailto:name@example.com`."""
    if not url:
        return "skipped"
    if url.lower().startswith("mailto:"):
        subject, body = _summary(payload)
        return _send_mail(k, url[7:].strip(), subject, body)
    try:
        web.resolve_public(url, k.settings.allow_private_urls)
        body = payload
        if (urlparse(url).hostname or "").lower() in _SLACK_HOSTS:
            subject, text = _summary(payload)
            body = {"text": f"*{subject}*\n{text}"}
        with httpx.Client(timeout=k.settings.url_timeout, transport=k.url_transport, follow_redirects=False) as c:
            r = c.post(url, json=body, headers={"User-Agent": "mka-webhook/3.1"})
        return "sent" if r.status_code < 300 else f"HTTP {r.status_code}"
    except (IngestError, httpx.HTTPError) as e:
        return f"failed: {str(e)[:120]}"


def webhook_url_ok(k, url: str) -> None:
    if url.lower().startswith("mailto:"):
        if not _EMAIL.match(url[7:].strip()):
            raise IngestError("That does not look like an e-mail address (use mailto:name@example.com)")
        if not k.settings.smtp_host:
            raise IngestError("E-mail notifications need MKA_SMTP_HOST to be configured on the server")
        return
    web.resolve_public(url, k.settings.allow_private_urls)  # raises IngestError


def _principal(db, user_id: str) -> Optional[Principal]:
    with db.session() as s:
        u = s.get(User, user_id)
        return Principal(u.id, u.tenant_id, u.role, u.email) if u and u.is_active else None


# ----------------------------------------------------------------------------- saved searches
def on_ingested(k, scope: Scope, meta: dict) -> int:
    """After a document became searchable: run every saved search of this workspace over it, create alerts for owners who may read it. Returns the number of alerts."""
    with k.db.session() as s:
        searches = list(s.scalars(select(SavedSearch).where(SavedSearch.tenant_id == scope.tenant, SavedSearch.workspace == scope.workspace)))
        s.expunge_all()
    n, st = 0, k.store(scope)
    for ss in searches:
        pr = _principal(k.db, ss.user_id)
        if pr is None or st.get_source(meta["id"], pr) is None:
            continue
        r = exact_search(st.iter_units([meta["id"]]), ss.term, case_sensitive=ss.case_sensitive, whole_word=ss.whole_word, max_excerpts=5)
        if not r.count:
            continue
        locs = list(dict.fromkeys(m["location"] for m in r.matches))[:10]
        with k.db.session() as s:
            s.add(Alert(tenant_id=scope.tenant, user_id=ss.user_id, saved_search_id=ss.id, term=ss.term, source_id=meta["id"], source_name=meta["name"], count=r.count, locations=locs))
        n += 1
        notify(k, ss.webhook_url, {"event": "saved_search_match", "term": ss.term, "document": meta["name"], "document_id": meta["id"], "occurrences": r.count, "locations": locs})
    return n


# ----------------------------------------------------------------------------- scheduled reports
def due(last: Optional[datetime], every_hours: int, now: datetime) -> bool:
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return now - last >= timedelta(hours=every_hours)


def run_schedule(k, assistant, sch: ReportSchedule) -> str:
    from .reports import build as builders
    from .reports.service import ReportTooLarge, generate

    pr = _principal(k.db, sch.user_id)
    if pr is None:
        return "owner is disabled or deleted"
    sp = sch.spec
    try:
        row = generate(k, assistant, pr, Scope(sch.tenant_id, sch.workspace), sp.get("kind", "summary"), sp.get("format", "pdf"), sp.get("source_ids"), sp.get("params") or {}, sp.get("title"))
    except (builders.ReportError, ReportTooLarge, KeyError) as e:
        return f"failed: {str(e.args[0] if e.args else e)[:200]}"
    note = notify(k, sch.webhook_url, {"event": "report_ready", "schedule": sch.name, "report_id": row.id, "title": row.title, "format": row.format, "size_bytes": row.size_bytes, "download_path": f"/reports/{row.id}/download"})
    return f"ok: report {row.id}" + ("" if note == "skipped" else f" (webhook {note})")


# ----------------------------------------------------------------------------- connectors
def _allowed_folder(k, raw: str) -> Path:
    root = k.settings.connector_root
    if not root:
        raise IngestError("Folder connectors are disabled (set MKA_CONNECTOR_ROOT to the directory they may read)")
    base = Path(root).resolve()
    p = (base / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if p != base and base not in p.parents:
        raise IngestError("The folder is outside the allowed connector root")
    if not p.is_dir():
        raise IngestError("The folder does not exist")
    return p


def validate_connector(k, kind: str, config: dict) -> dict:
    if kind == "folder":
        _allowed_folder(k, str(config.get("path", "")))
        return {"path": str(config["path"]), "recursive": bool(config.get("recursive", False))}
    if kind == "urls":
        urls = [u.strip() for u in config.get("urls", []) if isinstance(u, str) and u.strip()][:50]
        if not urls:
            raise IngestError("Give at least one URL")
        for u in urls:
            web.validate_url(u, k.settings.allow_private_urls)
        return {"urls": urls}
    if kind == "s3":
        try:
            import boto3  # noqa: F401
        except ImportError as e:
            raise IngestError("S3 connectors need the optional 'boto3' package (pip install boto3)") from e
        if not config.get("bucket"):
            raise IngestError("S3 connectors need a bucket")
        return {"bucket": str(config["bucket"]), "prefix": str(config.get("prefix", ""))}
    raise IngestError("kind must be folder, urls or s3")


def sync(k, c: Connector) -> dict:
    """Ingest what is new or changed (identical files are detected as duplicates; changed files become new versions)."""
    scope, res = Scope(c.tenant_id, c.workspace), {"ready": 0, "duplicate": 0, "failed": 0, "errors": [], "seen": 0}

    def take(r: dict, name: str):
        res[r["status"]] = res.get(r["status"], 0) + 1
        if r["status"] == "failed":
            res["errors"].append(f"{name}: {r['error']}"[:200])

    try:
        if c.kind == "folder":
            root = _allowed_folder(k, str(c.config.get("path", "")))
            files = sorted(p for p in (root.rglob("*") if c.config.get("recursive") else root.iterdir()) if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXT_KIND)[:MAX_SYNC_FILES]
            for p in files:
                if root not in p.resolve().parents:
                    continue  # a path that resolves outside the root is skipped
                res["seen"] += 1
                take(k.ingest_file(scope, p, p.name, owner_id=c.user_id), p.name)
        elif c.kind == "urls":
            for u in c.config.get("urls", [])[:50]:
                res["seen"] += 1
                take(k.ingest_url(scope, u, owner_id=c.user_id), u)
        elif c.kind == "s3":
            import boto3

            cli = boto3.client("s3")
            td = Path(tempfile.mkdtemp(prefix="mka-s3-"))
            try:
                for page in cli.get_paginator("list_objects_v2").paginate(Bucket=c.config["bucket"], Prefix=c.config.get("prefix", "")):
                    for obj in page.get("Contents", []):
                        name = obj["Key"].rsplit("/", 1)[-1]
                        if not name or Path(name).suffix.lower() not in EXT_KIND or res["seen"] >= MAX_SYNC_FILES or obj.get("Size", 0) > k.settings.max_upload_mb * 1024 * 1024:
                            continue
                        res["seen"] += 1
                        dest = td / name
                        cli.download_file(c.config["bucket"], obj["Key"], str(dest))
                        take(k.ingest_file(scope, dest, name, owner_id=c.user_id), name)
            finally:
                shutil.rmtree(td, ignore_errors=True)
    except IngestError as e:
        res["errors"].append(str(e))
    except Exception as e:  # noqa: BLE001  (a connector failure is reported, never raised into the scheduler)
        log.exception("connector %s failed", c.id)
        res["errors"].append(f"{type(e).__name__}: {str(e)[:150]}")
    return res
