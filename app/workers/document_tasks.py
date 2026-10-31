"""
Document ingestion Celery tasks.

Pipeline per document:
  1. Load file bytes from storage
  2. Parse text (PDF → pdfplumber, DOCX → python-docx, TXT/MD → plain read)
  3. Chunk text (sliding window: 512 tokens, 64 overlap)
  4. Embed chunks (SentenceTransformers all-MiniLM-L6-v2)
  5. Upsert into ChromaDB (tenant-scoped collection)
  6. Save DocumentChunk rows to PostgreSQL
  7. Update Document.status = 'ready'

Each step is wrapped in a try/except so failures update status to 'failed'
and record the error for debugging.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from celery import Task

from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


class BaseTask(Task):
    """Base task class with structured logging and common error handling."""

    abstract = True

    def on_failure(
        self, exc: Exception, task_id: str, args: list, kwargs: dict, einfo: object
    ) -> None:
        logger.error(
            "task_failed",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
        )


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.workers.document_tasks.ingest_document",
    max_retries=3,
    default_retry_delay=60,  # Retry after 60 seconds
    queue="ingestion",
)
def ingest_document(self: Task, document_id: str, tenant_id: str) -> dict:
    """
    Full document ingestion pipeline (sync Celery task wrapping async logic).

    Args:
        document_id: UUID string of the Document row.
        tenant_id:   UUID string of the Tenant (used for ChromaDB collection).

    Returns:
        {"status": "ready", "chunk_count": N}
    """
    logger.info(
        "ingestion_started",
        document_id=document_id,
        tenant_id=tenant_id,
        task_id=self.request.id,
    )

    try:
        # Run async ingestion logic in a fresh event loop
        result = asyncio.run(_run_ingestion(document_id, tenant_id))
        logger.info(
            "ingestion_complete",
            document_id=document_id,
            chunk_count=result["chunk_count"],
        )
        return result
    except Exception as exc:
        logger.exception(
            "ingestion_error",
            document_id=document_id,
            error=str(exc),
        )
        # Update document status to 'failed' (best-effort, fire-and-forget)
        asyncio.run(_mark_failed(document_id, str(exc)))
        raise self.retry(exc=exc)


async def _run_ingestion(document_id: str, tenant_id: str) -> dict:
    """
    Async ingestion pipeline.

    This is a placeholder — the real implementation will be built in
    Phase 3 (ingestion pipeline prompt). It exercises the DB session
    and verifies the async setup works end-to-end.
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionFactory
    from app.models.document import Document

    async with AsyncSessionFactory() as db:
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(document_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        # Mark as processing
        doc.status = "processing"
        await db.commit()

        # ── TODO: Phase 3 — implement parsing / chunking / embedding ──────
        # For now, immediately mark as ready with 0 chunks
        doc.status = "ready"
        doc.chunk_count = 0
        await db.commit()

        return {"status": "ready", "chunk_count": 0}


async def _mark_failed(document_id: str, error: str) -> None:
    """Update document status to 'failed' with error message."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionFactory
    from app.models.document import Document

    async with AsyncSessionFactory() as db:
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(document_id)))
        doc = result.scalar_one_or_none()
        if doc:
            doc.status = "failed"
            doc.error_message = error[:1000]  # Truncate for safety
            await db.commit()
