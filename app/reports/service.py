"""Create a report file + registry row. Used by POST /reports, by report schedules (scheduler process) and by tests."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from ..db import Report
from . import build as builders
from .render import render


class ReportTooLarge(ValueError):
    pass


def generate(k, assistant, principal, scope, kind: str, fmt: str, source_ids: Optional[list[str]], params: dict, title: Optional[str] = None) -> Report:
    """Raises builders.ReportError (bad request), KeyError (unknown source), ProviderError (model outage) or ReportTooLarge."""
    s = k.settings
    params = dict(params)
    if title:
        params["title"] = title
    t0 = time.perf_counter()
    doc = builders.build(kind, k, assistant, scope, principal, source_ids, params)
    if title and kind != "research":
        doc.title = title
    doc.generated_by = getattr(principal, "email", "") or principal.user_id
    data = render(doc, fmt, s.report_font)
    if len(data) > s.report_max_mb * 1024 * 1024:
        raise ReportTooLarge(f"The report would be larger than {s.report_max_mb} MB; narrow the selection")
    with k.db.session() as ses:
        row = Report(tenant_id=principal.tenant_id, user_id=principal.user_id, workspace=scope.workspace, kind=kind, format=fmt, title=doc.title[:300], status="ready",
                     params={**{a: b for a, b in params.items() if a != "questions"}, "questions": len(params.get("questions") or []), "source_ids": source_ids, "elapsed_ms": round((time.perf_counter() - t0) * 1000)},
                     size_bytes=len(data))
        ses.add(row)
        ses.flush()
        path = Path(s.data_dir) / "tenants" / principal.tenant_id / "reports" / f"{row.id}.{fmt}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        row.path = str(path)
        ses.flush()
        ses.expunge(row)
    return row
