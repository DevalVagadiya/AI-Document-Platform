"""
Documents API endpoints.

POST   /documents/upload         — upload a new document (multipart/form-data)
GET    /documents/               — list documents for current tenant
GET    /documents/{id}           — get document details
DELETE /documents/{id}           — delete document and its vectors
GET    /documents/{id}/status    — lightweight status polling for UI
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import AuthUser
from app.schemas.document import DocumentListItem, DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    current_user: AuthUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Upload a document for ingestion.

    Returns 202 Accepted immediately. The actual ingestion (parsing,
    chunking, embedding) runs asynchronously via Celery.
    """
    content = await file.read()
    mime_type = file.content_type or "application/octet-stream"

    service = DocumentService(db)
    doc = await service.save_upload(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        filename=file.filename or "unnamed",
        mime_type=mime_type,
        content=content,
    )

    # Dispatch Celery task (import here to avoid circular deps at module load)
    from app.workers.document_tasks import ingest_document

    ingest_document.delay(str(doc.id), str(current_user.tenant_id))

    return DocumentResponse.model_validate(doc)


@router.get("/", response_model=list[DocumentListItem])
async def list_documents(
    current_user: AuthUser,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentListItem]:
    """List all documents for the current tenant, newest first."""
    service = DocumentService(db)
    docs = await service.list_for_tenant(current_user.tenant_id, skip=skip, limit=limit)
    return [DocumentListItem.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Get full document details including status and chunk count."""
    service = DocumentService(db)
    doc = await service.get_by_id(document_id, current_user.tenant_id)
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Lightweight status endpoint for polling from the frontend.

    Returns only ``id``, ``status``, ``chunk_count``, and ``error_message``.
    """
    service = DocumentService(db)
    doc = await service.get_by_id(document_id, current_user.tenant_id)
    return {
        "id": str(doc.id),
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "error_message": doc.error_message,
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a document, its chunks (PostgreSQL), and its vectors (ChromaDB).

    ChromaDB deletion will be implemented in Phase 3 (RAG pipeline).
    """
    service = DocumentService(db)
    await service.delete(document_id, current_user.tenant_id)
