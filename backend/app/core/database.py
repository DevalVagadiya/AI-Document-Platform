"""
Async SQLAlchemy 2.0 engine and session factory.

Design decisions:
- asyncpg driver for maximum async throughput.
- Lazy engine initialization: the engine is only built when first accessed.
  This allows the module to be imported safely in test environments before
  DATABASE_URL is configured.
- get_db() is a FastAPI dependency that yields a session with auto commit/rollback.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Shared declarative base for all ORM models.

    All models inherit from this class.  Alembic reads ``Base.metadata``
    in ``alembic/env.py`` to auto-generate migrations.
    """


def _build_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """
    Factory for the async engine.

    Extracted so tests can pass a different URL (SQLite, in-memory, etc.)
    without monkey-patching module-level globals.
    """
    from app.core.config import get_settings

    s = get_settings()
    return create_async_engine(
        database_url,
        echo=s.DB_ECHO,
        pool_size=s.DB_POOL_SIZE,
        max_overflow=s.DB_MAX_OVERFLOW,
        pool_timeout=s.DB_POOL_TIMEOUT,
        pool_pre_ping=True,  # Detect stale connections automatically
        **kwargs,
    )


# ── Lazy singletons ────────────────────────────────────────────────────────────
# Engine and session factory are created on first access so that importing
# this module does NOT require DATABASE_URL to be set (important for tests).

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from app.core.config import get_settings

        s = get_settings()
        _engine = _build_engine(str(s.DATABASE_URL))
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


# Public aliases — used in Alembic env.py and health endpoints
@property  # type: ignore[misc]
def engine() -> AsyncEngine:
    return _get_engine()


# Alias for backward compatibility in workers and tasks
AsyncSessionFactory = property(lambda: _get_session_factory())  # type: ignore[assignment]


class _AsyncSessionFactoryProxy:
    """Proxy so ``AsyncSessionFactory()`` keeps working as a context manager."""

    def __call__(self) -> AsyncSession:
        return _get_session_factory()()

    def __class_getitem__(cls, item: Any) -> Any:
        return async_sessionmaker[item]


AsyncSessionFactory = _AsyncSessionFactoryProxy()  # type: ignore[assignment]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an ``AsyncSession`` per request.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    The session is automatically committed on success and rolled back on error.
    """
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_connection() -> AsyncGenerator[AsyncConnection, None]:
    """
    Yield a raw ``AsyncConnection`` for bulk operations or DDL statements.

    Prefer ``get_db`` (session) for normal CRUD operations.
    """
    async with _get_engine().connect() as conn:
        yield conn
