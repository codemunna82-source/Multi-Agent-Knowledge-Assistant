from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .rag.options import RetrievalOptions


class Citation(BaseModel):
    source_id: str
    source: str
    location: str
    excerpt: str
    score: Optional[float] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    source_ids: Optional[list[str]] = Field(default=None, description="Restrict to these sources (default: all in the session)")
    top_k: Optional[int] = Field(default=None, ge=1, le=30)
    case_sensitive: bool = False
    whole_word: bool = True
    conversation_id: Optional[str] = Field(default=None, max_length=32, description="Continue this conversation (default: the user's latest one in the workspace)")
    retrieval: Optional["RetrievalOptions"] = Field(default=None, description="Per-request RAG strategy overrides (mode, rewrite, multi_query, hyde, rerank, filters, ...)")


class AskResponse(BaseModel):
    answer: str
    route: str
    confidence: str  # high | medium | low | none
    verified: bool  # False when no reliable evidence was found
    citations: list[Citation] = []
    limitations: list[str] = []
    needs_input: bool = False
    details: dict[str, Any] = {}
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    followups: list[str] = []
    language: Optional[str] = None
    usage: dict[str, Any] = {}
    latency_ms: Optional[float] = None


class UrlRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)


class SourceInfo(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    created_at: str
    ingested_at: Optional[str] = None
    size_bytes: Optional[int] = None
    title: Optional[str] = None
    url: Optional[str] = None
    final_url: Optional[str] = None
    units: Optional[int] = None
    chunks: Optional[int] = None
    pages: Optional[int] = None
    tabular: bool = False
    tables: Optional[list[dict]] = None
    warnings: list[str] = []
    embedding: Optional[str] = None
    needs_reindex: bool = False
    owner_id: Optional[str] = None
    visibility: str = "tenant"


class IngestResult(BaseModel):
    status: str  # ready | failed
    name: str
    source: Optional[SourceInfo] = None
    error: Optional[str] = None


# ----------------------------------------------------------------------------- auth / admin / chat
import re as _re  # noqa: E402

_EMAIL = _re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class SignupRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(min_length=10, max_length=72)

    def model_post_init(self, _):
        if not _EMAIL.match(self.email):
            raise ValueError("invalid email")


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: str
    tenant_id: str
    email: str
    role: str
    is_active: bool = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=10, max_length=72)
    role: str = "viewer"

    def model_post_init(self, _):
        if not _EMAIL.match(self.email):
            raise ValueError("invalid email")
        if self.role not in ("viewer", "editor", "admin"):
            raise ValueError("role must be viewer, editor or admin")


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=10, max_length=72)

    def model_post_init(self, _):
        if self.role is not None and self.role not in ("viewer", "editor", "admin"):
            raise ValueError("role must be viewer, editor or admin")


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    meta: Optional[dict] = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    workspace: str
    title: str
    updated_at: str


class AuditOut(BaseModel):
    id: int
    ts: str
    user_id: Optional[str]
    action: str
    resource: Optional[str]
    outcome: str
    ip: Optional[str]
    request_id: Optional[str]
    detail: Optional[dict]


class PurgeRequest(BaseModel):
    confirm: str
