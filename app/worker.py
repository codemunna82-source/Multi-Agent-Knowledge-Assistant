"""Stand-alone ingestion worker:  python -m app.worker   (requires MKA_JOB_BACKEND=redis and MKA_REDIS_URL)."""
from __future__ import annotations

import signal
import threading

from .api import make_redis, setup_logging
from .config import get_settings
from .db import Database
from .jobs import JobService
from .security.audit import Auditor
from .service import Knowledge


def main() -> None:
    setup_logging()
    s = get_settings()
    db = Database(s.db_url)
    jobs = JobService(s, db, Knowledge(s), Auditor(db, s.audit_enabled), make_redis(s))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    jobs.work_forever(stop)


if __name__ == "__main__":
    main()
