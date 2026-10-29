from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MKA_", extra="ignore", populate_by_name=True)

    data_dir: str = "./data"
    max_upload_mb: int = 50

    # chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # providers
    llm_provider: str = "none"  # none | openai | gemini
    embedding_provider: str = "hash"  # hash | openai | gemini
    vector_store: str = "local"  # local | chroma
    openai_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "MKA_OPENAI_API_KEY"))
    gemini_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "MKA_GEMINI_API_KEY"))
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_chat_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "text-embedding-004"
    embed_batch: int = 64
    llm_timeout: float = 60.0

    # retrieval
    top_k: int = 6
    min_score: Optional[float] = None  # cosine gate; default depends on the embedder
    max_excerpts: int = 50

    # URL ingestion
    allow_private_urls: bool = False
    url_timeout: float = 15.0
    url_max_mb: int = 5
    url_max_redirects: int = 5

    # extraction
    ocr_enabled: bool = False

    @property
    def effective_min_score(self) -> float:
        if self.min_score is not None:
            return self.min_score
        return 0.12 if self.embedding_provider == "hash" else 0.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
