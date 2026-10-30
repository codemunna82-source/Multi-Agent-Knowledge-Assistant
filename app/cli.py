"""Operational commands:  python -m app.cli create-tenant --name ACME --email admin@acme.com"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .db import Database, Tenant, User
from .security.auth import hash_password


def create_tenant(name: str, email: str, password: str | None) -> str:
    s = get_settings()
    db = Database(s.db_url, run_migrations=True)
    pw = password or getpass.getpass("Admin password (min 10 chars): ")
    with db.session() as ses:
        if ses.scalar(select(User).where(User.email == email.lower())):
            raise SystemExit("A user with this email already exists")
        t = Tenant(name=name)
        ses.add(t)
        ses.flush()
        ses.add(User(tenant_id=t.id, email=email.lower(), password_hash=hash_password(pw), role="admin"))
        return t.id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-tenant")
    c.add_argument("--name", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--password", help="omit to be prompted (avoids shell history)")
    sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    sub.add_parser("backfill-registry", help="register documents found on the data volume but missing from PostgreSQL (upgrade from v2.0)")
    a = ap.parse_args(argv)
    if a.cmd == "create-tenant":
        print("tenant created:", create_tenant(a.name, a.email, a.password))
    elif a.cmd == "migrate":
        from .db import migrate

        migrate(get_settings().db_url)
        print("database is at head")
    elif a.cmd == "backfill-registry":
        from .registry import Registry

        st = get_settings()
        print("registered", Registry(Database(st.db_url, run_migrations=True)).backfill_from_disk(st.data_dir), "document(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
