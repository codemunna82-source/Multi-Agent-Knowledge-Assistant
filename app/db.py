"""Relational store (PostgreSQL in production, SQLite for dev/tests): identity, audit, jobs, conversations, eval."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, UTC
from typing import Iterator, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user")  # admin | manager | user
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefreshToken(Base):
    """Rotating refresh tokens (only the SHA-256 of the token is stored). `family_id` groups a rotation chain: presenting a token
    that was already rotated revokes the whole family (theft detection)."""

    __tablename__ = "refresh_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Document(Base):
    """Registry row per document VERSION (the ingested content lives on the data volume / vector store).
    `doc_key` is the logical document (stable across versions); only `is_current` versions are searchable."""

    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # source id
    tenant_id: Mapped[str] = mapped_column(String(64))
    workspace: Mapped[str] = mapped_column(String(64))
    doc_key: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(default=True)
    name: Mapped[str] = mapped_column(String(2048))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ready")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(32), default="anonymous")
    visibility: Mapped[str] = mapped_column(String(12), default="tenant")  # tenant | private | restricted
    classification: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace", "doc_key", "version", name="uq_document_version"),
        Index("ix_documents_scope_current", "tenant_id", "workspace", "is_current"),
        Index("ix_documents_scope_hash", "tenant_id", "workspace", "content_hash"),
        Index("ix_documents_doc_key", "doc_key"),
        Index("ix_documents_created", "tenant_id", "created_at"),
    )


class DocumentPermission(Base):
    """Sharing of a logical document with a user or a role (used when visibility == 'restricted')."""

    __tablename__ = "document_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    doc_key: Mapped[str] = mapped_column(String(32))
    principal_type: Mapped[str] = mapped_column(String(8))  # user | role
    principal_id: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(8), default="read")  # read | write
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("doc_key", "principal_type", "principal_id", name="uq_doc_permission"), Index("ix_docperm_tenant_doc", "tenant_id", "doc_key"))


class TenantSettings(Base):
    __tablename__ = "tenant_settings"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    retention_days_documents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # None = keep forever
    retention_days_conversations: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retention_days_audit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retention_days_reports: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    web_allowed: Mapped[bool] = mapped_column(default=True)
    web_allowed_domains: Mapped[list] = mapped_column(JSON, default=list)  # empty = any public domain
    redact_stored_messages: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MemoryFact(Base):
    """Opt-in long-term memory: short notes a user explicitly asked the assistant to remember (never inferred automatically)."""

    __tablename__ = "memory_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UserPref(Base):
    __tablename__ = "user_prefs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    memory_enabled: Mapped[bool] = mapped_column(default=True)  # conversation memory (history window + summary)
    long_term_memory: Mapped[bool] = mapped_column(default=False)  # saved facts are recalled into prompts only when True
    theme: Mapped[str] = mapped_column(String(8), default="system")


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))  # summary | executive | comparison | research | analytics
    format: Mapped[str] = mapped_column(String(8))  # pdf | docx | xlsx
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="ready")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_reports_tenant_created", "tenant_id", "created_at"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))  # file | url | reindex
    name: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|ready|failed
    stage: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    workspace: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    memory_enabled: Mapped[bool] = mapped_column(default=True)  # False = private chat: nothing is stored or recalled
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # rolling memory of older turns
    summary_upto: Mapped[int] = mapped_column(Integer, default=0)  # number of leading messages already folded into `summary`
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # route, citations, confidence, ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    name: Mapped[str] = mapped_column(String(200), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


Index("ix_messages_conv_id", Message.conversation_id, Message.id)
Index("ix_audit_tenant_ts", AuditEvent.tenant_id, AuditEvent.ts)
Index("ix_jobs_tenant_created", Job.tenant_id, Job.created_at)
Index("ix_conversations_scope", Conversation.tenant_id, Conversation.user_id, Conversation.workspace, Conversation.updated_at)


def migrate(url: str) -> None:
    """Apply Alembic migrations up to head (serialised across replicas with a PostgreSQL advisory lock)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.attributes["url"] = url
    eng = create_engine(url, future=True, poolclass=StaticPool if ":memory:" in url else None) if url.startswith("sqlite") else create_engine(url, future=True)
    with eng.connect() as conn:
        if conn.dialect.name == "postgresql":
            conn.exec_driver_sql("SELECT pg_advisory_lock(727274)")
        try:
            command.upgrade(cfg, "head")
        finally:
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SELECT pg_advisory_unlock(727274)")
    eng.dispose()


class Database:
    def __init__(self, url: str, run_migrations: bool = False):
        kw: dict = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kw["poolclass"] = StaticPool
        self.engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _fk(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
        self._sm = sessionmaker(self.engine, expire_on_commit=False, future=True)
        if run_migrations:  # production: schema is owned by Alembic
            migrate(url)
        else:  # development / tests: create tables directly (kept identical to the migrations by `alembic check` in the test-suite)
            Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sm()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()


# ----------------------------------------------------------------------------- v3.1: feedback, automation, annotations, connectors, MFA
class Feedback(Base):
    """Thumbs up/down on an answer. The question text is stored only when the user chose to (needed to turn failures into evaluation cases)."""

    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    rating: Mapped[int] = mapped_column(Integer)  # +1 / -1
    route: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{"source","location"}] cited in the answer
    expected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # what the user says the answer should contain
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_feedback_tenant_created", "tenant_id", "created_at"),)


class SavedSearch(Base):
    """A literal term watched across newly ingested documents; matches create alerts."""

    __tablename__ = "saved_searches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    workspace: Mapped[str] = mapped_column(String(64))
    term: Mapped[str] = mapped_column(String(200))
    whole_word: Mapped[bool] = mapped_column(default=True)
    case_sensitive: Mapped[bool] = mapped_column(default=False)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    saved_search_id: Mapped[str] = mapped_column(String(32))
    term: Mapped[str] = mapped_column(String(200))
    source_id: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(2048))
    count: Mapped[int] = mapped_column(Integer)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    seen: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_alerts_user_seen", "user_id", "seen"),)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict] = mapped_column(JSON)  # the POST /reports body
    every_hours: Mapped[int] = mapped_column(Integer)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    doc_key: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(32))
    loc: Mapped[dict] = mapped_column(JSON)
    quote: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(String(2000), default="")
    kind: Mapped[str] = mapped_column(String(10), default="comment")  # comment | highlight | bookmark
    shared: Mapped[bool] = mapped_column(default=False)  # visible to everyone who can read the document
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_annotations_scope_doc", "tenant_id", "doc_key"),)


class Connector(Base):
    """Keeps a workspace in sync with an external place: a mounted folder, a list of URLs, or an S3 prefix (optional boto3)."""

    __tablename__ = "connectors"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12))  # folder | urls | s3
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON)
    every_hours: Mapped[int] = mapped_column(Integer, default=24)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UserMfa(Base):
    """TOTP second factor (RFC 6238). `enabled` becomes true only after the user proved they hold the secret."""

    __tablename__ = "user_mfa"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    secret: Mapped[str] = mapped_column(String(255))  # base32 seed, or "enc1:<fernet token>" when MKA_DATA_KEY is set
    enabled: Mapped[bool] = mapped_column(default=False)
    last_counter: Mapped[int] = mapped_column(Integer, default=0)  # replay protection: a code is accepted once
    recovery_hashes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OidcIdentity(Base):
    __tablename__ = "oidc_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_oidc_subject"),)


# ----------------------------------------------------------------------------- AI Learning Academy (per user; no FK so the open dev mode's "anonymous" user works too)
class AcademyProgress(Base):
    __tablename__ = "academy_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    lesson_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | done
    step: Mapped[int] = mapped_column(Integer, default=0)  # resume point: index of the last section the learner reached
    bookmarked: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_academy_progress"),)


class AcademyQuizAttempt(Base):
    __tablename__ = "academy_quiz_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    lesson_id: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str] = mapped_column(String(96))
    correct: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AcademyExercise(Base):
    __tablename__ = "academy_exercises"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    lesson_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # exercise | debug
    passed: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", "kind", name="uq_academy_exercise"),)


class AcademyActivity(Base):
    __tablename__ = "academy_activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (UTC)
    count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_academy_activity"),)


class AcademyProject(Base):
    __tablename__ = "academy_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64))
    done_steps: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_academy_project"),)
