"""Periodic maintenance runner:  python -m app.scheduler [--once] [--dry-run]

Only one replica runs the tasks at a time: a Redis lock (MKA_REDIS_URL) or, on PostgreSQL, a session advisory lock. On SQLite (single node)
no lock is needed. The interval is MKA_SCHEDULER_INTERVAL_S (default 3600)."""
from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import threading
from typing import Iterator

from . import maintenance
from .api import make_redis, setup_logging
from .config import get_settings
from .db import Database
from .security.audit import Auditor
from .service import Knowledge

log = logging.getLogger("mka.scheduler")
LOCK_KEY = 727275


@contextlib.contextmanager
def leader_lock(db: Database, redis_client, ttl: int) -> Iterator[bool]:
    """Yields True when this process is the leader for the current round."""
    if redis_client is not None:
        got = bool(redis_client.set("mka:scheduler:lock", "1", nx=True, ex=ttl))
        try:
            yield got
        finally:
            if got:
                redis_client.delete("mka:scheduler:lock")
    elif db.engine.dialect.name == "postgresql":
        from sqlalchemy import text

        with db.engine.connect() as conn:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
            try:
                yield got
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()
    else:
        yield True


def run_round(k: Knowledge, auditor: Auditor, redis_client, dry_run: bool = False) -> dict | None:
    with leader_lock(k.db, redis_client, ttl=max(60, k.settings.scheduler_interval_s)) as leader:
        if not leader:
            log.info("another scheduler instance holds the lock; skipping this round")
            return None
        res = maintenance.run(k, dry_run=dry_run, auditor=auditor)
        log.info("maintenance round finished: %s", res)
        return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one round and exit")
    ap.add_argument("--dry-run", action="store_true", help="report what would be removed without deleting")
    a = ap.parse_args()
    setup_logging()
    s = get_settings()
    db = Database(s.db_url)
    k = Knowledge(s, db=db)
    auditor, redis_client = Auditor(db, s.audit_enabled), make_redis(s)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        run_round(k, auditor, redis_client, a.dry_run)
        if a.once:
            break
        stop.wait(s.scheduler_interval_s)


if __name__ == "__main__":
    main()
