"""
Query (RAG) Pydantic schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import AppBaseModel


class QueryRequest(AppBaseModel):
    question: str = Field(min_length=3, max_length=2000)
    document_id: uuid.UUID = Field(..., description="Document ID is required to scope the query")
    max_chunks: int = Field(default=5, ge=1, le=20)
    strict_search: bool = False  # If True uses similarity threshold 0.35, else 0.20


class ChunkMatch(AppBaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    similarity_score: float


class QueryResponse(AppBaseModel):
    query_id: uuid.UUID
    question: str
    answer: str
    sources: list[ChunkMatch]
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


class QueryLogResponse(AppBaseModel):
    id: uuid.UUID
    question: str
    answer: str | None
    chunks_retrieved: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    error: str | None
    created_at: datetime
