"""
QueryLog ORM model.

Records every RAG query for analytics, billing, debugging, and abuse detection.

Design:
- Append-only table — rows are never updated.
- ``latency_ms`` is the end-to-end wall-clock time of the query pipeline.
- ``chunks_retrieved`` records how many vectors were returned above the
  similarity threshold.
- ``prompt_tokens`` / ``completion_tokens`` map directly to Gemini billing units.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import GUID, TimestampMixin, new_uuid


class QueryLog(Base, TimestampMixin):
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # Query payload
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # RAG telemetry
    chunks_retrieved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Error tracking
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<QueryLog id={self.id} tenant={self.tenant_id}>"
