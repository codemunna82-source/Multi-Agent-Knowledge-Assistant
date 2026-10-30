"""Relational store (PostgreSQL in production, SQLite for dev/tests): identity, audit, jobs, conversations, eval."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(timezone.utc)


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
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin | editor | viewer
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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


class Database:
    def __init__(self, url: str):
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
