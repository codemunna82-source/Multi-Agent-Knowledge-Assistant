from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- auth
    auth_enabled: bool = False  # dev default keeps the original open API; production requires True
    allow_signup: bool = True  # POST /auth/signup creates a tenant + admin; disable in production
    jwt_secret: Optional[SecretStr] = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
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
    corrective: bool = True
    max_retries: int = 2  # bounded corrective / verification retries

    # --- agents
    supervisor_mode: str = "rules"  # rules | llm
    checkpoint_backend: str = "memory"  # memory | sqlite
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
    vision_captions: bool = False  # multimodal: caption images via the configured vision-capable LLM

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
