"""
Tenant ORM model.

A Tenant represents an organisation that subscribes to the platform.
All other resources (users, documents, vector collections) are scoped to a tenant.

Design:
- ``slug`` is URL-safe and used as the ChromaDB collection prefix
  (``{slug}_documents``) to provide hard isolation without running separate
  ChromaDB instances.
- ``plan`` controls feature flags and usage limits.
- ``is_active = False`` effectively suspends the entire tenant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, new_uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(50), default="starter", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob

    # Relationships
    users: Mapped[list[User]] = relationship(  # noqa: F821
        "User", back_populates="tenant", lazy="raise"
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        "Document", back_populates="tenant", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug!r}>"
