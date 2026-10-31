"""
Shared ORM base class, mixins, and cross-database types.

Using SQLAlchemy 2.0 ``Mapped`` / ``mapped_column`` syntax throughout.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base  # noqa: F401  (re-exported for convenience)


# ── Cross-database UUID type ──────────────────────────────────────────────────


class GUID(sa.TypeDecorator):
    """
    Platform-independent UUID type.

    - PostgreSQL: uses the native ``UUID`` type (efficient, indexed).
    - SQLite / other: stored as ``CHAR(36)`` string.

    This allows the same models to work in production (PostgreSQL) and in
    unit tests (SQLite in-memory) without any changes.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))



class TimestampMixin:
    """
    Adds ``created_at`` and ``updated_at`` columns to any model.

    - ``created_at``: set by the database on INSERT (server_default).
    - ``updated_at``: maintained by SQLAlchemy's ``onupdate`` hook.

    Both store timezone-aware UTC datetimes.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


def new_uuid() -> uuid.UUID:
    """Generate a new random UUID (used as column default)."""
    return uuid.uuid4()
