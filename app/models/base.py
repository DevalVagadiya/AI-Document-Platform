"""
Shared ORM base class and mixins.

Using SQLAlchemy 2.0 ``Mapped`` / ``mapped_column`` syntax throughout.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base  # noqa: F401  (re-exported for convenience)


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
