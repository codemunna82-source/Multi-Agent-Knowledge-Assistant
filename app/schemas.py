from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


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


class IngestResult(BaseModel):
    status: str  # ready | failed
    name: str
    source: Optional[SourceInfo] = None
    error: Optional[str] = None
