import asyncio
import logging
import uuid
import tiktoken

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import anyio

from app.core.config import settings
from app.models.document import Document
from app.models.chunk import DocumentChunk
from app.services.storage_service import storage_service
from app.services.embedding_service import embedding_service
from app.services.vector_service import vector_service
from app.utils.parsers import extract_text_from_file
from app.utils.chunking import chunk_text

logger = logging.getLogger(__name__)


async def process_document_task(document_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession):
    """
    Background task to process a document (parsing, chunking, embedding, indexing).
    Currently called via BackgroundTasks, but will move to Celery in Phase 6.
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
        # 2. Extract text from file
        abs_path = storage_service.get_absolute_path(document.storage_path)
        # Run synchronous text extraction in a thread to prevent blocking the async loop
        raw_text = await anyio.to_thread.run_sync(
            extract_text_from_file, str(abs_path), document.mime_type
        )

        if not raw_text:
            raise ValueError("Extracted text is empty.")

        # 3. Chunk text
        # Run chunking in a thread (tiktoken can be CPU intensive for large texts)
        text_chunks = await anyio.to_thread.run_sync(
            chunk_text, raw_text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP
        )

        if not text_chunks:
            raise ValueError("No chunks were generated from the text.")

        # 4. Generate embeddings
        # Run embedding model in a thread (CPU bound)
        embeddings = await anyio.to_thread.run_sync(
            embedding_service.embed_texts, text_chunks
        )

        # 5. Create DocumentChunk ORM models
        db_chunks = []
        enc = tiktoken.get_encoding("cl100k_base")
        for idx, text_content in enumerate(text_chunks):
            # Calculate tokens exactly
            token_count = len(enc.encode(text_content))
            
            chunk = DocumentChunk(
                document_id=document.id,
                tenant_id=document.tenant_id,
                chunk_index=idx,
                content=text_content,
                token_count=token_count,
                chroma_id=f"{document.id}:{idx}",
                embedding_model=settings.EMBEDDING_MODEL
            )
            db.add(chunk)
            db_chunks.append(chunk)

        # Flush to get the UUIDs for chunks (needed for VectorService)
        await db.flush()

        # 6. Save chunks to ChromaDB
        # VectorService handles it synchronously (ChromaDB Python client is mostly sync)
        await anyio.to_thread.run_sync(
            vector_service.add_chunks, 
            document.tenant_id, 
            document.id, 
            db_chunks, 
            embeddings
        )

        # 7. Update document status
        document.chunk_count = len(db_chunks)
        document.status = "ready"
        logger.info(f"Successfully processed document {document_id} into {len(db_chunks)} chunks.")

    except Exception as e:
        logger.exception(f"Failed to process document {document_id}: {e}")
        document.status = "failed"
        document.error_message = str(e)
    
    finally:
        # Commit the final status (ready or failed)
        await db.commit()
