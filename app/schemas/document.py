"""
Document and Chunk Pydantic schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import AppBaseModel, TimestampSchema


class DocumentResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    status: str
    chunk_count: int
    error_message: str | None = None


class DocumentListItem(AppBaseModel):
    """Lightweight response for list endpoints."""

    id: uuid.UUID
    filename: str
    status: str
    chunk_count: int
    file_size_bytes: int
    created_at: datetime


class ChunkResponse(AppBaseModel):
    id: uuid.UUID
    chunk_index: int
    content: str
    token_count: int
    chroma_id: str
