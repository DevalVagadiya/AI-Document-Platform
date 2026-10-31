"""
Query (RAG) API endpoints.

POST /queries/           — ask a question (RAG pipeline)
GET  /queries/           — query history for current tenant
GET  /queries/{id}       — get a specific query log entry
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import AuthUser
from app.schemas.query import QueryLogResponse, QueryRequest, QueryResponse

router = APIRouter(prefix="/queries", tags=["Queries"])


@router.post("/", response_model=QueryResponse, status_code=200)
async def ask_question(
    body: QueryRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """
    Execute a RAG query against the tenant's document collection.

    Pipeline (full implementation in Phase 3):
    1. Embed the question using SentenceTransformers
    2. Retrieve top-k chunks from ChromaDB
    3. Filter by similarity threshold
    4. Build prompt with retrieved context
    5. Stream answer from Gemini 2.5 Flash
    6. Log query + metrics to PostgreSQL

    Returns the answer and source chunk references.
    """
    # Stub response — real implementation in Phase 3
    stub_id = uuid.uuid4()
    return QueryResponse(
        query_id=stub_id,
        question=body.question,
        answer="RAG pipeline not yet implemented. Coming in Phase 3.",
        sources=[],
        latency_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
    )


@router.get("/", response_model=list[QueryLogResponse])
async def list_queries(
    current_user: AuthUser,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[QueryLogResponse]:
    """List query history for the current tenant, newest first."""
    from sqlalchemy import select

    from app.models.query_log import QueryLog

    result = await db.execute(
        select(QueryLog)
        .where(QueryLog.tenant_id == current_user.tenant_id)
        .offset(skip)
        .limit(limit)
        .order_by(QueryLog.created_at.desc())
    )
    return [QueryLogResponse.model_validate(q) for q in result.scalars().all()]
