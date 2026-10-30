"""Read-only SQL over the uploaded tables, executed in an in-memory SQLite database that is locked down by SQLite's *authorizer*.

Defence in depth (a generated or user-supplied query is never trusted):
  1. text checks: one statement, SELECT/WITH only, no comments, bounded length;
  2. authorizer: only SELECT/READ of the loaded tables and a whitelist of scalar/aggregate/window functions - everything else
     (ATTACH, PRAGMA, INSERT/UPDATE/DELETE/DDL, load_extension, sqlite_master reads, recursive CTEs) is denied by SQLite itself;
  3. SQLITE_LIMIT_* caps, `PRAGMA query_only`, a wall-clock deadline enforced through the progress handler, and a result-row cap.
No Python from the query or from an LLM is ever executed."""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..tools.tabular import Table
from .insights import date_columns

ALLOWED_FUNCTIONS = {
    "abs", "round", "upper", "lower", "length", "substr", "substring", "coalesce", "ifnull", "nullif", "trim", "ltrim", "rtrim", "replace", "instr", "min", "max",
    "sum", "avg", "count", "total", "group_concat", "strftime", "date", "datetime", "julianday", "typeof", "iif", "sign", "cast", "like", "glob", "random_never",
    "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value", "ntile", "percent_rank", "cume_dist", "nth_value",
}
MAX_SQL = 4000


class SqlError(ValueError):
    """The SQL was rejected or failed; the message is safe to show to the user."""


@dataclass
class Schema:
    name: str  # SQL table name
    source: str
    sheet: Optional[str]
    columns: dict  # sql column name -> {"original", "type"}
    rows: int


@dataclass
class Sandbox:
    conn: sqlite3.Connection
    schemas: list[Schema] = field(default_factory=list)
    table_meta: dict = field(default_factory=dict)  # sql table name -> (source_id, source, sheet)

    def describe(self) -> list[dict]:
        return [{"table": s.name, "source": s.source, "sheet": s.sheet, "rows": s.rows,
                 "columns": [{"name": k, "original": v["original"], "type": v["type"]} for k, v in s.columns.items()]} for s in self.schemas]


def _slug(s: str, fallback: str) -> str:
    out = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    if not out:
        out = fallback
    return out if not out[0].isdigit() else f"_{out}"


def build(tables: list[Table]) -> Sandbox:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    sb = Sandbox(conn)
    used: set[str] = set()
    for t in tables:
        base = _slug(t.source.rsplit(".", 1)[0] + ("_" + t.sheet if t.sheet else ""), "table")
        name, n = base, 2
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        dates = date_columns(t)
        cols: dict = {"_row": {"original": "spreadsheet row number", "type": "INTEGER"}}
        data: dict = {"_row": [int(i) for i in t.df.index]}
        seen = {"_row"}
        for i, c in enumerate(t.df.columns):
            sc, k = _slug(str(c), f"col{i}"), 2
            while sc in seen:
                sc, k = f"{sc}_{k}", k + 1
            seen.add(sc)
            if c in t.numeric:
                typ, vals = "REAL", [None if pd.isna(v) else float(v) for v in t.df[c]]
            elif c in dates:
                typ, vals = "TEXT", [None if pd.isna(v) else v.strftime("%Y-%m-%d") for v in dates[c]]
            else:
                typ, vals = "TEXT", [str(v) for v in t.df[c]]
            cols[sc] = {"original": str(c), "type": typ + (" (date, ISO)" if c in dates else "")}
            data[sc] = vals
        ddl = ", ".join(f'"{k}" {v["type"].split()[0]}' for k, v in cols.items())
        conn.execute(f'CREATE TABLE "{name}" ({ddl})')
        keys = list(cols)
        conn.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * len(keys))})', zip(*(data[k] for k in keys)))
        sb.schemas.append(Schema(name, t.source, t.sheet, cols, len(t.df)))
        sb.table_meta[name] = (t.source_id, t.source, t.sheet)
    conn.commit()
    allowed_tables = {s.name for s in sb.schemas}

    def authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if arg1 in allowed_tables else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (arg2 or "").lower() in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY  # everything else, incl. PRAGMA, ATTACH, DML/DDL, RECURSIVE

    conn.execute("PRAGMA query_only = ON")
    for lim, val in ((sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000), (sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL), (sqlite3.SQLITE_LIMIT_COLUMN, 64),
                     (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 40), (sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 5), (sqlite3.SQLITE_LIMIT_FUNCTION_ARG, 8),
                     (sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, 100), (sqlite3.SQLITE_LIMIT_ATTACHED, 0)):
        conn.setlimit(lim, val)
    conn.set_authorizer(authorizer)
    return sb


def check_sql(sql: str) -> str:
    """Text-level validation; returns the normalised statement."""
    s = (sql or "").strip()
    s = s[:-1].strip() if s.endswith(";") else s
    if not s:
        raise SqlError("Empty query")
    if len(s) > MAX_SQL:
        raise SqlError(f"Query longer than {MAX_SQL} characters")
    if "--" in s or "/*" in s or ";" in s or "\x00" in s:
        raise SqlError("Comments and multiple statements are not allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise SqlError("Only SELECT queries are allowed")
    if re.search(r"(?i)\b(attach|detach|pragma|insert|update|delete|drop|alter|create|replace\s+into|vacuum|reindex|load_extension|sqlite_master|sqlite_schema|sqlite_temp_master)\b", re.sub(r"'[^']*'", "''", s)):
        raise SqlError("Query uses a keyword that is not allowed in read-only analysis")
    return s


def run(sb: Sandbox, sql: str, max_rows: int = 1000, timeout_s: float = 3.0) -> dict:
    s = check_sql(sql)
    deadline = time.monotonic() + timeout_s
    sb.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
    try:
        cur = sb.conn.execute(s)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as e:
        msg = str(e)
        if "interrupted" in msg:
            raise SqlError(f"Query exceeded the {timeout_s:g}s time limit") from e
        raise SqlError(f"SQL error: {msg}") from e
    except sqlite3.DatabaseError as e:
        msg = str(e)
        raise SqlError("The query uses an operation or table that is not permitted" if "not authorized" in msg else f"SQL error: {msg}") from e
    finally:
        sb.conn.set_progress_handler(None, 0)
    truncated = len(rows) > max_rows
    return {"sql": s, "columns": cols, "rows": [list(r) for r in rows[:max_rows]], "row_count": min(len(rows), max_rows), "truncated": truncated}


def cited_rows(sb: Sandbox, sql_result: dict, limit: int = 20) -> list[dict]:
    """Citation rows when the query selected `_row` from a single-source result (otherwise the answer carries no per-row citations)."""
    cols = sql_result["columns"]
    if "_row" not in cols:
        return []
    ri = cols.index("_row")
    m = re.search(r'(?i)\bfrom\s+"?([a-z0-9_]+)"?', sql_result["sql"])
    meta = sb.table_meta.get(m.group(1)) if m else None
    if not meta:
        return []
    sid, source, sheet = meta
    out = []
    for r in sql_result["rows"][:limit]:
        if r[ri] is None:
            continue
        item = {"source_id": sid, "source": source, "row": int(r[ri]), "values": {c: v for c, v in zip(cols, r) if c != "_row"}}
        if sheet is not None:
            item["sheet"] = sheet
        out.append(item)
    return out
