"""Typed application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="APP_",
        extra="ignore",
    )

    app_name: str = "Medical Document Assistant"
    env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_key: str | None = None
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )
    max_upload_mb: int = Field(default=20, ge=1, le=100)
    upload_rate_limit: int = Field(default=10, ge=1, le=120)
    question_rate_limit: int = Field(default=20, ge=1, le=120)

    data_dir: Path = PROJECT_ROOT / ".data"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size_words: int = Field(default=240, ge=50, le=500)
    chunk_overlap_words: int = Field(default=30, ge=0, le=100)
    top_k: int = Field(default=8, ge=1, le=20)
    max_context_chars: int = Field(default=16_000, ge=2_000, le=100_000)

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "APP_OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = Field(default=120.0, ge=5.0, le=600.0)

    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "APP_LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "APP_LANGFUSE_SECRET_KEY"),
    )
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices(
            "LANGFUSE_BASE_URL",
            "LANGFUSE_HOST",
            "APP_LANGFUSE_BASE_URL",
        ),
    )
    langfuse_capture_content: bool = False

    @model_validator(mode="after")
    def validate_chunking(self) -> Settings:
        """Ensure overlapping chunks always make forward progress."""

        if self.chunk_overlap_words >= self.chunk_size_words:
            msg = "chunk_overlap_words must be smaller than chunk_size_words"
            raise ValueError(msg)
        if self.env == "production" and not (self.api_key or "").strip():
            msg = "APP_API_KEY is required when APP_ENV=production"
            raise ValueError(msg)
        if self.env == "production" and any(
            origin == "*" for origin in self.allowed_origin_list
        ):
            msg = "Wildcard CORS origins are not allowed in production"
            raise ValueError(msg)
        return self

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def prompt_path(self) -> Path:
        return PROJECT_ROOT / "prompts" / "answer.jinja"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.chroma_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one settings object per process."""

    settings = Settings()
    settings.ensure_directories()
    return settings
