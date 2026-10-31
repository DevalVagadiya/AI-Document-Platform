"""
Document ORM model.

Represents a file uploaded by a user. The document goes through a lifecycle:
  pending → processing → ready | failed

Design:
- Storage path is stored relative to the configured storage root.
  The storage service translates it to an absolute path or S3 key.
- ``checksum`` (SHA-256) enables duplicate detection within a tenant.
- ``chunk_count`` is denormalised here for quick display; it mirrors the
  actual number of DocumentChunk rows.
- ``error_message`` stores the last ingestion error for debugging.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import GUID, TimestampMixin, new_uuid

DocumentStatus = Literal["pending", "processing", "ready", "failed"]

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    }
)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # File metadata
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Processing state
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped[Tenant] = relationship(  # noqa: F821
        "Tenant", back_populates="documents", lazy="raise"
    )
    uploaded_by: Mapped[User] = relationship(  # noqa: F821
        "User", back_populates="documents", lazy="raise"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(  # noqa: F821
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.filename!r} status={self.status!r}>"
