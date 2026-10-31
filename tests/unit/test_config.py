"""
Unit tests for app/core/config.py
"""

from __future__ import annotations


def test_settings_loads_without_env(monkeypatch):
    """Settings with all required values provided inline should construct successfully."""
    from app.core.config import Settings

    s = Settings(  # type: ignore[call-arg]
        APP_NAME="Test",
        SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        GEMINI_API_KEY="test",
        REDIS_URL="redis://localhost:6379/0",
    )
    assert s.APP_NAME == "Test"
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 15


def test_database_url_sync_conversion():
    """Sync URL should replace asyncpg driver with psycopg2."""
    from app.core.config import Settings

    s = Settings(  # type: ignore[call-arg]
        APP_NAME="Test",
        SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        GEMINI_API_KEY="test",
        REDIS_URL="redis://localhost:6379/0",
    )
    assert "psycopg2" in s.database_url_sync
    assert "asyncpg" not in s.database_url_sync


def test_pem_newline_decoding():
    """\\n in PEM env var should be decoded to real newlines."""
    from app.core.config import Settings

    s = Settings(  # type: ignore[call-arg]
        APP_NAME="Test",
        SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\ntest\\n-----END RSA PRIVATE KEY-----",
        JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----",
        GEMINI_API_KEY="test",
        REDIS_URL="redis://localhost:6379/0",
    )
    assert "\n" in s.JWT_PRIVATE_KEY


def test_max_file_size_bytes():
    """max_file_size_bytes property should correctly convert MB to bytes."""
    from app.core.config import Settings

    s = Settings(  # type: ignore[call-arg]
        APP_NAME="Test",
        SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        GEMINI_API_KEY="test",
        REDIS_URL="redis://localhost:6379/0",
        MAX_FILE_SIZE_MB=10,
    )
    assert s.max_file_size_bytes == 10 * 1024 * 1024
