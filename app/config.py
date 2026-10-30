from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Docker/Kubernetes secrets: any of these may be supplied as <NAME>_FILE=/run/secrets/xyz instead of the value itself
FILE_SECRETS = {"jwt_secret": "MKA_JWT_SECRET", "openai_api_key": "OPENAI_API_KEY", "gemini_api_key": "GEMINI_API_KEY", "qdrant_api_key": "MKA_QDRANT_API_KEY",
                "brave_api_key": "BRAVE_API_KEY", "database_url": "MKA_DATABASE_URL", "redis_url": "MKA_REDIS_URL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MKA_", extra="ignore", populate_by_name=True)

    env: str = "dev"  # dev | production (production enforces secure settings, see validate_production)
    data_dir: str = "./data"
    max_upload_mb: int = 50
    max_pdf_pages: int = 5000

    # --- database / cache / queue
    database_url: Optional[str] = None  # default: sqlite in data_dir; use postgresql+psycopg2://... in production
    redis_url: Optional[str] = None  # rate limiting + job queue; falls back to in-process when unset
    job_backend: str = "inprocess"  # inprocess | redis
    job_workers: int = 2
    job_max_attempts: int = 3  # bounded retries for transient failures (embedding API outage ...)
    job_retry_backoff: float = 2.0
    job_stale_minutes: int = 30  # 'running' jobs older than this are re-queued by the worker on start

    auto_migrate: bool = False  # run Alembic migrations at start-up (always on when MKA_ENV=production)
    max_versions_per_document: int = 5  # older versions beyond this are pruned (content + vectors)
    allow_duplicate_uploads: bool = False  # identical file already indexed in the workspace -> reported as duplicate, not re-ingested

    # --- auth
    auth_enabled: bool = False  # dev default keeps the original open API; production requires True
    allow_signup: bool = True  # POST /auth/signup creates a tenant + admin; disable in production
    jwt_secret: Optional[SecretStr] = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cors_origins: str = ""  # comma separated; empty = same-origin only

    # --- rate limiting ("N/second|minute|hour")
    rate_limit_enabled: bool = True
    rate_limit_ask: str = "30/minute"
    rate_limit_ingest: str = "20/minute"
    rate_limit_auth: str = "10/minute"

    # --- chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150
    parent_max_chars: int = 3000

    # --- providers
    llm_provider: str = "none"  # none | openai | gemini
    embedding_provider: str = "hash"  # hash | openai | gemini
    vector_store: str = "local"  # local | chroma | qdrant
    qdrant_url: Optional[str] = None  # None + qdrant_path => embedded mode (dev/tests)
    qdrant_path: Optional[str] = None
    qdrant_api_key: Optional[SecretStr] = None
    openai_api_key: Optional[SecretStr] = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "MKA_OPENAI_API_KEY"))
    gemini_api_key: Optional[SecretStr] = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "MKA_GEMINI_API_KEY"))
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_transcribe_model: str = "whisper-1"
    gemini_chat_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "text-embedding-004"
    embed_batch: int = 64
    llm_timeout: float = 60.0
    # USD per 1M tokens (input, output) used for cost estimates; override per deployment
    price_table: str = "gpt-4o-mini=0.15:0.60,gemini-2.0-flash=0.10:0.40,text-embedding-3-small=0.02:0,text-embedding-004=0:0"

    # --- retrieval (all overridable per request via `retrieval`)
    top_k: int = 6
    min_score: Optional[float] = None
    max_excerpts: int = 50
    retrieval_mode: str = "hybrid"  # semantic | keyword | hybrid
    query_rewrite: bool = True
    multi_query: bool = False
    multi_query_n: int = 3
    hyde: bool = False
    parent_child: bool = True
    compression: bool = True
    reranker: str = "lexical"  # none | lexical | llm | cross_encoder
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    graph_rag: bool = False  # expand retrieval with chunks linked through the entity knowledge graph
    cross_lingual: bool = True  # (needs an LLM) add translated query variants when the question language differs from the documents'
    corrective: bool = True
    max_retries: int = 2  # bounded corrective / verification retries

    # --- agents
    supervisor_mode: str = "rules"  # rules | llm
    web_enabled: bool = True  # Web Agent may fetch URLs that appear in a question (SSRF-guarded)
    web_search_provider: str = "none"  # none | searxng | brave
    web_search_url: Optional[str] = None  # SearXNG base URL
    brave_api_key: Optional[SecretStr] = None
    web_fallback: bool = False  # when indexed sources cannot answer, try web search (needs a provider)
    checkpoint_backend: str = "memory"  # memory | sqlite | postgres (postgres uses MKA_DATABASE_URL)
    memory_turns: int = 10

    # --- security
    allow_private_urls: bool = False
    url_timeout: float = 15.0
    url_max_mb: int = 5
    url_max_redirects: int = 5
    url_ca_bundle: Optional[str] = None
    injection_policy: str = "flag"  # flag | exclude  (exclude: suspicious chunks never reach the LLM)
    audit_enabled: bool = True

    # --- extraction
    ocr_enabled: bool = False
    ocr_languages: str = "eng"
    pdf_engine: str = "auto"  # auto (PyMuPDF if installed) | pypdf
    pdf_heading_max_pages: int = 400  # font-size heading detection (when a PDF has no bookmarks) runs only up to this many pages
    pdf_tables: bool = True  # structured table extraction from PDFs (pdfplumber); exposed via /sources/{id}/tables
    pdf_tables_max_pages: int = 300
    max_zip_uncompressed_mb: int = 500  # zip-bomb guard for .docx/.xlsx
    vision_captions: bool = False  # multimodal: caption images via the configured vision-capable LLM

    @model_validator(mode="before")
    @classmethod
    def _read_secret_files(cls, data):
        data = dict(data or {})
        for field, env in FILE_SECRETS.items():
            path = os.environ.get(f"{env}_FILE")
            if path and field not in data and env not in os.environ:
                try:
                    data[field] = Path(path).read_text(encoding="utf-8").strip()
                except OSError as e:
                    raise ValueError(f"{env}_FILE points to an unreadable file: {e.strerror}") from e
        return data

    @property
    def effective_min_score(self) -> float:
        if self.min_score is not None:
            return self.min_score
        return 0.12 if self.embedding_provider == "hash" else 0.3

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        from pathlib import Path

        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{Path(self.data_dir).resolve()}/mka.db"

    def secret(self, name: str) -> Optional[str]:
        v = getattr(self, name)
        return v.get_secret_value() if v is not None else None

    def validate_production(self) -> None:
        if self.env != "production":
            return
        problems = []
        if not self.auth_enabled:
            problems.append("MKA_AUTH_ENABLED must be true")
        js = self.secret("jwt_secret")
        if not js or len(js) < 32:
            problems.append("MKA_JWT_SECRET must be set to a random string of at least 32 characters")
        if self.allow_private_urls:
            problems.append("MKA_ALLOW_PRIVATE_URLS must be false")
        if self.allow_signup:
            problems.append("MKA_ALLOW_SIGNUP must be false (create tenants with `python -m app.cli create-tenant`)")
        if "*" in self.cors_origins:
            problems.append("MKA_CORS_ORIGINS must not contain '*'")
        if self.db_url.startswith("sqlite"):
            problems.append("MKA_DATABASE_URL must point to PostgreSQL")
        if problems:
            raise RuntimeError("Insecure production configuration: " + "; ".join(problems))

    def jwt_key(self) -> str:
        key = self.secret("jwt_secret")
        if key:
            return key
        if not hasattr(self, "_ephemeral"):
            object.__setattr__(self, "_ephemeral", secrets.token_urlsafe(48))  # dev only: tokens die with the process
        return self._ephemeral

    def public_dict(self) -> dict:
        """Effective configuration with every secret masked (used by the admin settings page)."""
        out = {}
        for k, v in self.model_dump().items():
            out[k] = ("***set***" if v else None) if isinstance(v, SecretStr) or "key" in k or "secret" in k or k == "database_url" else v
        out["database_url"] = self.db_url.split("@")[-1] if "@" in self.db_url else self.db_url
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
