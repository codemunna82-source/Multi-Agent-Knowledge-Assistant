"""Generates docs/openapi.json and docs/API.md from the live FastAPI app (so the docs cannot drift from the code)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402

app = create_app(Settings(data_dir=tempfile.mkdtemp(), _env_file=None))
spec = app.openapi()
(root / "docs" / "openapi.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")

PERM = {  # minimum role per route family (see app/security/auth.py PERMISSIONS): user < manager < admin
    "/auth": "public (signup/login/refresh) / any user", "/health": "public", "/metrics": "metrics bearer token or admin",
    "/sources": "user (read, preview, compare) · manager (upload, URL, re-index, versions, sharing, delete own) · admin (delete any)",
    "/jobs": "manager", "/ask": "user", "/conversations": "user (own conversations only)", "/graph": "user", "/transcribe": "user",
    "/search": "user", "/summaries": "user", "/compare": "user", "/analytics": "user", "/web": "user", "/reports": "user (own reports; admin: whole organisation)",
    "/memory": "user (own data)", "/eval": "manager", "/admin/maintenance": "admin", "/admin": "admin", "/session": "admin",
}
by_tag: dict[str, list] = {}
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        by_tag.setdefault((op.get("tags") or ["other"])[0], []).append((method.upper(), path, op))

out = ["# API reference", "", "Generated from the running application (`python scripts/gen_api_docs.py`). Interactive docs: `GET /docs` (Swagger UI) and `GET /redoc`;",
       "machine-readable: [`openapi.json`](openapi.json).", "",
       "**Conventions** — `Authorization: Bearer <JWT>` (when `MKA_AUTH_ENABLED=true`); `X-Session-ID: <workspace>` selects the document workspace inside your tenant "
       "(default `default`); `X-Request-ID` is echoed back and stored in the audit log; errors are `{ \"detail\": ... }` with 401/403/404/409/413/422/429/502 as appropriate; "
       "`429` carries `Retry-After`.", ""]
for tag in sorted(by_tag):
    out += [f"## {tag}", ""]
    for method, path, op in sorted(by_tag[tag], key=lambda x: (x[1], x[0])):
        role = next((v for k, v in PERM.items() if path.startswith(k)), "")
        out.append(f"### `{method} {path}`")
        if op.get("summary") and op["summary"].lower().replace("_", " ") != path.strip("/").replace("/", " "):
            pass
        doc = (op.get("description") or "").strip().splitlines()
        if doc:
            out += ["", " ".join(l.strip() for l in doc if l.strip())]
        params = [f"`{p['name']}` ({p['in']}{', required' if p.get('required') else ''})" for p in op.get("parameters", [])]
        if params:
            out += ["", "Parameters: " + ", ".join(params)]
        body = op.get("requestBody", {}).get("content", {})
        for ctype, c in body.items():
            ref = c.get("schema", {}).get("$ref", "").split("/")[-1]
            out += ["", f"Body: `{ctype}`" + (f" → `{ref}`" if ref else "")]
        resp = ", ".join(sorted(op.get("responses", {})))
        out += ["", f"Responses: {resp}" + (f" · Access: {role}" if role else ""), ""]
(root / "docs" / "API.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"{sum(len(v) for v in by_tag.values())} operations documented")
