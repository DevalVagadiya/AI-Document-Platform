"""
Pytest configuration and shared fixtures.

Design decisions:
- Settings are patched via environment variables BEFORE any app module imports
  to avoid ValidationError in CI / local runs without a .env file.
- AsyncClient from httpx for testing async FastAPI endpoints.
- In-memory SQLite (aiosqlite) for fast, isolated DB tests.
- Each test gets a fresh DB via function-scoped fixture.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Inject test env vars BEFORE any app imports ───────────────────────────────
# This prevents the module-level `settings = get_settings()` from failing.
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-32-chars!!")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault(
    "JWT_PRIVATE_KEY",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAtestkey\n-----END RSA PRIVATE KEY-----",
)
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgQefAtestpubkey\n-----END PUBLIC KEY-----",
)
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-api-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Now safe to import app modules
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402

# ── Settings override for tests ───────────────────────────────────────────────


def override_settings() -> Settings:
    """Return test-safe settings using env vars set above."""
    get_settings.cache_clear()
    return get_settings()


# ── Async test configuration ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio policy."""
    return asyncio.DefaultEventLoopPolicy()


# ── In-memory SQLite engine for unit tests ────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a test database session backed by SQLite in-memory.

    Each test gets a clean schema via create_all / drop_all.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── FastAPI test client ───────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def test_app(db_session: AsyncSession) -> FastAPI:
    """
    Create the FastAPI app with dependency overrides for testing.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest_asyncio.fixture()
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client bound to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac
