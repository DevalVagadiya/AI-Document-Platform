import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthUser, get_db
from app.core.exceptions import FileTooLargeError, NotFoundError, UnsupportedFileTypeError
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.document_service import DocumentService
from app.workers.ingestion_tasks import process_document_task

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
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e))
    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Trigger background parsing & embedding (Will be replaced with Celery in Phase 6)
    # background_tasks.add_task(process_document_task, document.id, current_user.tenant_id, db)

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
    """List all documents for the current tenant with pagination."""
    service = DocumentService(db)
    items, total = await service.list_for_tenant(
        tenant_id=current_user.tenant_id, skip=skip, limit=limit
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
        return DocumentResponse.model_validate(document)
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
        await service.delete(document_id, current_user.tenant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
