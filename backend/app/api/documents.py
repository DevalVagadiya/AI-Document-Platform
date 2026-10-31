import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthUser, get_db
from app.core.exceptions import FileTooLargeError, NotFoundError, UnsupportedFileTypeError
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
async def upload_document(
    current_user: AuthUser,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Upload a document for processing.
    The document will be securely stored and isolated to the current user's tenant.
    A background task will immediately begin indexing the document for search.
    """
    service = DocumentService(db)
    try:
        document = await service.save_upload(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            file=file,
        )
        # Commit immediately so background workers can find the document in DB
        await db.commit()
        await db.refresh(document)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e))
    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Dispatch to Celery worker if available; otherwise fallback to FastAPI BackgroundTasks
    try:
        from app.workers.document_tasks import ingest_document
        ingest_document.delay(str(document.id), str(current_user.tenant_id))
    except Exception:
        from app.workers.document_tasks import _run_ingestion
        background_tasks.add_task(_run_ingestion, str(document.id), str(current_user.tenant_id))

    return DocumentResponse.model_validate(document)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
)
async def list_documents(
    current_user: AuthUser,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents for the current user (or all tenant documents if admin) with pagination."""
    service = DocumentService(db)
    user_id_filter = None if current_user.is_admin else current_user.id
    items, total = await service.list_for_tenant(
        tenant_id=current_user.tenant_id,
        user_id=user_id_filter,
        skip=skip,
        limit=limit,
    )
    from app.schemas.document import DocumentListItem
    validated_items = [DocumentListItem.model_validate(item) for item in items]
    
    return DocumentListResponse(
        items=validated_items,
        total=total,
        page=(skip // limit) + 1 if limit > 0 else 1,
        size=limit,
        pages=(total + limit - 1) // limit if limit > 0 else 1,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
async def get_document(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Retrieve metadata for a specific document."""
    service = DocumentService(db)
    try:
        document = await service.get_by_id(document_id, current_user.tenant_id)
        if not current_user.is_admin and document.uploaded_by_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return DocumentResponse.model_validate(document)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{document_id}/view",
    summary="View/Stream raw document file",
)
async def view_document(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
):
    """Serve the original document file for inline browser viewing or downloading."""
    from fastapi.responses import FileResponse
    from app.services.storage_service import storage_service

    service = DocumentService(db)
    try:
        document = await service.get_by_id(document_id, current_user.tenant_id)
        if not current_user.is_admin and document.uploaded_by_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        
        abs_path = storage_service.get_absolute_path(document.storage_path)
        if not abs_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file missing on disk")

        return FileResponse(
            path=abs_path,
            media_type=document.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"inline; filename=\"{document.original_filename or document.filename}\""
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a document and its chunks."""
    service = DocumentService(db)
    try:
        document = await service.get_by_id(document_id, current_user.tenant_id)
        if not current_user.is_admin and document.uploaded_by_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        await service.delete(document_id, current_user.tenant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
