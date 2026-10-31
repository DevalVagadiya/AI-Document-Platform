"""
APIKey ORM model.

Supports machine-to-machine authentication without JWT rotation overhead.

Design:
- Only the SHA-256 hash is stored — the plaintext is shown once on creation.
- ``prefix`` (first 16 chars of plaintext, e.g. ``adp_ab12cd34...``) is stored
  for display in key management UIs without exposing the secret.
- ``last_used_at`` is updated (async, best-effort) on every authenticated request.
- ``expires_at = NULL`` means the key never expires.
- UUID columns use the custom GUID TypeDecorator (PostgreSQL native / SQLite CHAR).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin, new_uuid


class APIKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)  # Human label
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # Display only
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship
    user: Mapped[User] = relationship(  # noqa: F821
        "User", back_populates="api_keys", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<APIKey id={self.id} prefix={self.key_prefix!r} active={self.is_active}>"
