import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


async def process_document_task(document_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession):
    """
    Background task to process a document (parsing, chunking, embedding, indexing).
    Currently a stub for Phase 4. Will be fully implemented in Phase 5.
    """
    logger.info(f"Starting background ingestion for document {document_id}")

    # 1. Fetch document and mark as processing
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        logger.error(f"Document {document_id} not found for ingestion.")
        return

    document.status = "processing"
    await db.commit()

    try:
        # Simulate processing time
        await asyncio.sleep(2)

        # TODO (Phase 5):
        # 1. Load file from storage_service
        # 2. Extract text based on mime_type (pdf, docx, etc.)
        # 3. Chunk text (e.g. 512 tokens with overlap)
        # 4. Generate embeddings via SentenceTransformers
        # 5. Save chunks to ChromaDB (with tenant_id prefix)
        # 6. Save DocumentChunk rows to SQL DB
        # 7. Update document.chunk_count

        document.status = "ready"
        logger.info(f"Successfully processed document {document_id}")

    except Exception as e:
        logger.exception(f"Failed to process document {document_id}: {e}")
        document.status = "failed"
        document.error_message = str(e)
    
    finally:
        # Commit the final status (ready or failed)
        await db.commit()
