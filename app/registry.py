"""PostgreSQL-backed document registry: versions, content hashes, ownership and sharing (ACL).
The ingested content (units, chunks, vectors, original file) stays on the data volume / vector store; this registry is the source of
truth for *which documents exist, in which version, and who may see them*."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import delete, func, select, update

from .db import Database, Document, DocumentPermission, now

PRIVILEGED = "admin"


def can_see(meta: dict, principal, acl: dict) -> bool:
    """Document-level access control. visibility: tenant (everyone) | private (owner) | restricted (owner + shared users/roles). Admins see all."""
    if principal is None or principal.role == PRIVILEGED:
        return True
    vis = meta.get("visibility", "tenant")
    if vis == "tenant":
        return True
    if meta.get("owner_id") == principal.user_id:
        return True
    if vis == "restricted":
        return principal.user_id in acl.get("users", ()) or principal.role in acl.get("roles", ())
    return False


class Registry:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _meta(row: Document) -> dict:
        m = dict(row.meta or {})
        m.update(id=row.id, doc_key=row.doc_key, version=row.version, is_current=row.is_current, name=row.name, kind=row.kind, owner_id=row.owner_id,
                 visibility=row.visibility, content_hash=row.content_hash)  # classification stays the full dict stored in meta (the column holds only its label, for SQL filters)
        return m

    def _acl_map(self, s, tenant: str, doc_keys: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {k: {"users": set(), "roles": set()} for k in doc_keys}
        if doc_keys:
            for p in s.scalars(select(DocumentPermission).where(DocumentPermission.tenant_id == tenant, DocumentPermission.doc_key.in_(doc_keys))):
                out[p.doc_key]["users" if p.principal_type == "user" else "roles"].add(p.principal_id)
        return out

    # ------------------------------------------------------------------ reads
    def list(self, scope, principal=None, include_old: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace)
            if not include_old:
                q = q.where(Document.is_current.is_(True))
            rows = list(s.scalars(q.order_by(Document.created_at, Document.name, Document.id)))
            restricted = [r.doc_key for r in rows if r.visibility == "restricted"]
            acl = self._acl_map(s, scope.tenant, restricted)
            return [self._meta(r) for r in rows if can_see(self._meta(r), principal, acl.get(r.doc_key, {}))]

    def get(self, scope, source_id: str, principal=None) -> Optional[dict]:
        with self.db.session() as s:
            r = s.get(Document, source_id)
            if not r or r.tenant_id != scope.tenant or r.workspace != scope.workspace:
                return None
            m = self._meta(r)
            acl = self._acl_map(s, scope.tenant, [r.doc_key]).get(r.doc_key, {}) if r.visibility == "restricted" else {}
            return m if can_see(m, principal, acl) else None  # hidden documents look exactly like missing ones

    def signature(self, scope) -> tuple:
        """Cheap change signature for in-memory indexes (count + latest update)."""
        with self.db.session() as s:
            n, last, cur = s.execute(select(func.count(Document.id), func.max(Document.updated_at), func.sum(Document.is_current.cast(Integer_))).where(
                Document.tenant_id == scope.tenant, Document.workspace == scope.workspace)).one()
            return (n, str(last), cur)

    def versions(self, scope, doc_key: str) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.doc_key == doc_key).order_by(Document.version.desc()))
            return [self._meta(r) for r in rows]

    def find_by_hash(self, scope, content_hash: str) -> Optional[dict]:
        with self.db.session() as s:
            r = s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.content_hash == content_hash,
                                                 Document.is_current.is_(True)).limit(1)).first()
            return self._meta(r) if r else None

    def find_by_text_hash(self, scope, text_hash: str, exclude_id: str = "") -> Optional[dict]:
        with self.db.session() as s:
            r = s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.text_hash == text_hash,
                                                 Document.is_current.is_(True), Document.id != exclude_id).limit(1)).first()
            return self._meta(r) if r else None

    def current_by_name(self, scope, name: str) -> Optional[dict]:
        with self.db.session() as s:
            r = s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.name == name, Document.is_current.is_(True)).limit(1)).first()
            return self._meta(r) if r else None

    def acl(self, scope, doc_key: str) -> dict:
        with self.db.session() as s:
            a = self._acl_map(s, scope.tenant, [doc_key])[doc_key]
            return {"users": sorted(a["users"]), "roles": sorted(a["roles"])}

    # ------------------------------------------------------------------ writes
    def register(self, scope, meta: dict) -> None:
        """Insert/update the registry row for a freshly committed version; makes it the current version of its document and
        demotes older versions in the same transaction."""
        with self.db.session() as s:
            row = s.get(Document, meta["id"])
            vals = dict(tenant_id=scope.tenant, workspace=scope.workspace, doc_key=meta["doc_key"], version=meta.get("version", 1), is_current=True, name=meta["name"], kind=meta["kind"],
                        status=meta.get("status", "ready"), content_hash=meta.get("content_hash"), text_hash=meta.get("text_hash"), size_bytes=meta.get("size_bytes"),
                        owner_id=meta.get("owner_id", "anonymous"), visibility=meta.get("visibility", "tenant"), classification=(meta.get("classification") or {}).get("label") if isinstance(meta.get("classification"), dict) else meta.get("classification"),
                        language=meta.get("language"), meta={k: v for k, v in meta.items() if k not in ("injection_flags",)} | ({"injection_flags": meta["injection_flags"]} if meta.get("injection_flags") else {}))
            if row is None:
                s.add(Document(id=meta["id"], **vals))
            else:
                for k, v in vals.items():
                    setattr(row, k, v)
                row.updated_at = now()
            s.flush()
            s.execute(update(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.doc_key == meta["doc_key"], Document.id != meta["id"]).values(is_current=False, updated_at=now()))

    def update_meta(self, scope, source_id: str, **fields) -> None:
        with self.db.session() as s:
            r = s.get(Document, source_id)
            if r and r.tenant_id == scope.tenant:
                m = dict(r.meta or {})
                m.update(fields)
                r.meta = m
                for k in ("visibility", "owner_id", "classification", "language"):
                    if k in fields:
                        setattr(r, k, fields[k] if not isinstance(fields[k], dict) else fields[k].get("label"))
                r.updated_at = now()

    def remove(self, scope, source_id: str) -> Optional[dict]:
        """Delete a version row; if it was current, the newest remaining version becomes current again. Returns the promoted meta (if any).
        When the last version goes, the document's permissions go with it."""
        with self.db.session() as s:
            r = s.get(Document, source_id)
            if not r or r.tenant_id != scope.tenant or r.workspace != scope.workspace:
                return None
            key, was_current = r.doc_key, r.is_current
            s.delete(r)
            s.flush()
            promoted = None
            if was_current:
                nxt = s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.doc_key == key).order_by(Document.version.desc()).limit(1)).first()
                if nxt:
                    nxt.is_current = True
                    nxt.updated_at = now()
                    promoted = self._meta(nxt)
            if s.scalar(select(func.count(Document.id)).where(Document.tenant_id == scope.tenant, Document.doc_key == key)) == 0:
                s.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == scope.tenant, DocumentPermission.doc_key == key))
            return promoted

    def set_current(self, scope, source_id: str) -> None:
        with self.db.session() as s:
            r = s.get(Document, source_id)
            if not r or r.tenant_id != scope.tenant or r.workspace != scope.workspace:
                return
            s.execute(update(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.doc_key == r.doc_key).values(is_current=False, updated_at=now()))
            r.is_current = True
            r.updated_at = now()

    def set_visibility(self, scope, doc_key: str, visibility: str, users: list[str], roles: list[str]) -> None:
        with self.db.session() as s:
            rows = list(s.scalars(select(Document).where(Document.tenant_id == scope.tenant, Document.workspace == scope.workspace, Document.doc_key == doc_key)))
            for r in rows:
                r.visibility = visibility
                m = dict(r.meta or {})
                m["visibility"] = visibility
                r.meta = m
                r.updated_at = now()
            s.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == scope.tenant, DocumentPermission.doc_key == doc_key))
            if visibility == "restricted":
                s.add_all([DocumentPermission(tenant_id=scope.tenant, doc_key=doc_key, principal_type="user", principal_id=u) for u in dict.fromkeys(users)])
                s.add_all([DocumentPermission(tenant_id=scope.tenant, doc_key=doc_key, principal_type="role", principal_id=r_) for r_ in dict.fromkeys(roles)])

    def delete_scope(self, tenant: str, workspace: Optional[str] = None) -> int:
        with self.db.session() as s:
            q = delete(Document).where(Document.tenant_id == tenant)
            if workspace:
                q = q.where(Document.workspace == workspace)
            n = s.execute(q).rowcount
            if not workspace:
                s.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == tenant))
            return n

    # ------------------------------------------------------------------ upgrade path from v2.0 (documents only on disk)
    def backfill_from_disk(self, data_dir: str | Path) -> int:
        """Register sources that exist on the data volume but not in PostgreSQL (upgrade from a v2.0 deployment)."""
        import json

        from .storage import Scope

        n = 0
        root = Path(data_dir) / "tenants"
        for meta_path in sorted(root.glob("*/workspaces/*/sources/*/meta.json")):
            tenant, workspace = meta_path.parts[-6], meta_path.parts[-4]
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            with self.db.session() as s:
                if s.get(Document, meta["id"]):
                    continue
            meta.setdefault("doc_key", meta["id"])
            meta.setdefault("version", 1)
            self.register(Scope(tenant, workspace), meta)
            n += 1
        return n


from sqlalchemy import Integer as Integer_  # noqa: E402  (kept at the bottom: only used in `signature`)
