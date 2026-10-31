from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..config import Settings


class MetadataFilter(BaseModel):
    kinds: Optional[list[str]] = Field(default=None, description="pdf, csv, xlsx, docx, txt, md, json, url, image")
    name_contains: Optional[str] = Field(default=None, max_length=200)
    page_min: Optional[int] = Field(default=None, ge=1)
    page_max: Optional[int] = Field(default=None, ge=1)
    sheet: Optional[str] = Field(default=None, max_length=200)
    section_contains: Optional[str] = Field(default=None, max_length=200)
    ingested_after: Optional[str] = Field(default=None, description="ISO date/time")
    ingested_before: Optional[str] = None

    def active(self) -> bool:
        return any(v is not None for v in self.model_dump().values())


class RetrievalOptions(BaseModel):
    """Per-request overrides; anything left unset falls back to the server defaults (MKA_*)."""

    mode: Optional[Literal["semantic", "keyword", "hybrid"]] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=30)
    rewrite: Optional[bool] = None
    multi_query: Optional[bool] = None
    hyde: Optional[bool] = None
    parent_child: Optional[bool] = None
    compression: Optional[bool] = None
    reranker: Optional[Literal["none", "lexical", "llm", "cross_encoder"]] = None
    corrective: Optional[bool] = None
    graph: Optional[bool] = None
    cross_lingual: Optional[bool] = None
    auto: Optional[bool] = Field(default=None, description="Let the agent graph choose the retrieval strategy for this question: candidate configurations are tried and the best-scoring one is used")
    self_rag: Optional[bool] = Field(default=None, description="Self-RAG loop: retrieve-or-not, passage relevance grading, sentence-level support critique with bounded regeneration")
    max_retries: Optional[int] = Field(default=None, ge=0, le=4)
    filters: Optional[MetadataFilter] = None


@dataclass
class Resolved:
    mode: str = "hybrid"
    top_k: int = 6
    rewrite: bool = True
    multi_query: bool = False
    multi_query_n: int = 3
    hyde: bool = False
    parent_child: bool = True
    compression: bool = True
    reranker: str = "lexical"
    corrective: bool = True
    graph: bool = False
    cross_lingual: bool = True
    auto: bool = False
    self_rag: bool = False
    self_rag_rounds: int = 1
    max_retries: int = 2
    filters: MetadataFilter = field(default_factory=MetadataFilter)
    min_score: float = 0.12
    parent_max_chars: int = 3000
    injection_policy: str = "flag"
    pool: int = 0

    def __post_init__(self):
        self.pool = self.pool or max(self.top_k * 4, 20)


def resolve(s: Settings, o: Optional[RetrievalOptions] = None, **force) -> Resolved:
    o = o or RetrievalOptions()
    pick = lambda name, default: getattr(o, name) if getattr(o, name) is not None else default  # noqa: E731
    r = Resolved(
        mode=pick("mode", s.retrieval_mode), top_k=pick("top_k", s.top_k), rewrite=pick("rewrite", s.query_rewrite),
        multi_query=pick("multi_query", s.multi_query), multi_query_n=s.multi_query_n, hyde=pick("hyde", s.hyde),
        parent_child=pick("parent_child", s.parent_child), compression=pick("compression", s.compression),
        reranker=pick("reranker", s.reranker), corrective=pick("corrective", s.corrective), graph=pick("graph", s.graph_rag),
        cross_lingual=pick("cross_lingual", s.cross_lingual), self_rag=pick("self_rag", s.self_rag), auto=pick("auto", s.auto_retrieval), self_rag_rounds=s.self_rag_rounds, max_retries=pick("max_retries", s.max_retries),
        filters=o.filters or MetadataFilter(), min_score=s.effective_min_score, parent_max_chars=s.parent_max_chars,
        injection_policy=s.injection_policy,
    )
    for k, v in force.items():
        setattr(r, k, v)
    return r
