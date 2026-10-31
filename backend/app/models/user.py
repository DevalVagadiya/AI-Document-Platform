"""
User ORM model.

Users belong to exactly one Tenant. Roles are stored as a PostgreSQL TEXT[]
array, which SQLAlchemy maps to a Python list.

Design:
- ``roles`` uses JSON type for cross-database compatibility (SQLite + PostgreSQL).
- ``password_hash`` is nullable because OAuth/SSO users have no local password.
- ``last_login_at`` is updated by the auth service on successful login.
- UUID columns use the custom GUID TypeDecorator (PostgreSQL native / SQLite CHAR).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin, new_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant: Mapped[Tenant] = relationship(  # noqa: F821
        "Tenant", back_populates="users", lazy="raise"
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        "Document", back_populates="uploaded_by", lazy="raise"
    )
    api_keys: Mapped[list[APIKey]] = relationship(  # noqa: F821
        "APIKey", back_populates="user", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
