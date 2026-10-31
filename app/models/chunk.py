"""
DocumentChunk ORM model.

Stores the text chunks extracted from a document after ingestion.
Each chunk maps to a vector in ChromaDB.

Design:
- ``chroma_id`` is the primary key used in ChromaDB. Using a deterministic
  format (``{document_id}:{chunk_index}``) enables easy re-embedding without
  orphaned vectors.
- ``embedding_model`` records which model was used — critical for migrations
  when upgrading embedding models.
- ``token_count`` helps the RAG service stay within LLM context window limits.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, new_uuid


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Position within the document
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Vector store reference
    chroma_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationship
    document: Mapped[Document] = relationship(  # noqa: F821
        "Document", back_populates="chunks", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"
