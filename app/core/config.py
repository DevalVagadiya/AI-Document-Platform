"""
Application configuration via Pydantic Settings.

All values are read from environment variables or a .env file.
Validation happens at startup — a missing required var crashes fast and loudly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object. One instance per process (cached)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_NAME: str = "AI Document Platform"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    # Secret used for CSRF tokens / misc signing (NOT the JWT key).
    SECRET_KEY: str = Field(min_length=32)

    # ── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False  # Set True only in development for SQL logging

    # ── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = "redis://localhost:6379/0"  # type: ignore[assignment]

    # ── ChromaDB ────────────────────────────────────────────────────────────
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000

    # ── JWT (RS256) ─────────────────────────────────────────────────────────
    # Store PEM content with literal \n (will be decoded in validator).
    JWT_PRIVATE_KEY: str
    JWT_PUBLIC_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @field_validator("JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY", mode="before")
    @classmethod
    def decode_pem_newlines(cls, v: str) -> str:
        """Allow \\n escape sequences in env var PEM keys."""
        return v.replace("\\n", "\n")

    # ── Gemini ──────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_MAX_OUTPUT_TOKENS: int = 8192
    GEMINI_TEMPERATURE: float = 0.2

    # ── SentenceTransformers ────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384  # Fixed for all-MiniLM-L6-v2

    # ── File Storage ─────────────────────────────────────────────────────────
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    LOCAL_STORAGE_PATH: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50

    # S3 / MinIO (required only when STORAGE_BACKEND=s3)
    S3_BUCKET: str = "doc-platform-files"
    S3_ENDPOINT_URL: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"

    # ── Rate Limits ──────────────────────────────────────────────────────────
    RATE_LIMIT_QUERIES_PER_HOUR: int = 100
    RATE_LIMIT_UPLOADS_PER_DAY: int = 50

    # ── RAG Settings ─────────────────────────────────────────────────────────
    MAX_CHUNKS_PER_QUERY: int = 5
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    SIMILARITY_THRESHOLD: float = 0.35

    # ── Celery ───────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # ── Computed helpers ─────────────────────────────────────────────────────
    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def database_url_sync(self) -> str:
        """Synchronous DSN for Alembic (uses psycopg2)."""
        return str(self.DATABASE_URL).replace("postgresql+asyncpg://", "postgresql+psycopg2://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Using @lru_cache means the .env file is read exactly once.
    Call ``get_settings.cache_clear()`` in tests to reset state.
    """
    return Settings()  # type: ignore[call-arg]



# Module-level convenience alias.
# IMPORTANT: This will raise ValidationError if the required env vars
# are not set. In tests, override get_settings via dependency injection
# or set the TEST_MODE env var before importing this module.
#
# Usage: from app.core.config import settings
# Or:    from app.core.config import get_settings; s = get_settings()
try:
    settings: Settings = get_settings()
except Exception:  # noqa: BLE001
    # In test environments without a .env file, settings is None.
    # Tests must patch get_settings or set required env vars.
    settings = None  # type: ignore[assignment]
