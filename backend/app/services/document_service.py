"""
Document service — upload, status, list, delete.

Ingestion (parsing, chunking, embedding) is handled asynchronously by the
Celery worker (app/workers/document_tasks.py).  This service only manages
the metadata lifecycle.
"""

from __future__ import annotations

import uuid
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    FileTooLargeError,
    NotFoundError,
    TenantMismatchError,
    UnsupportedFileTypeError,
)
from app.models.document import ALLOWED_MIME_TYPES, Document
from app.services.storage_service import storage_service


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save_upload(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        file: UploadFile,
    ) -> Document:
        """
        Validate, stream to disk, prevent duplicates, and create the Document row.
        """
        mime_type = file.content_type or "application/octet-stream"
        if mime_type not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileTypeError(
                f"File type {mime_type!r} not supported. Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            )

        # Stream file to storage and calculate checksum & size securely without OOM
        relative_path, checksum, size_bytes = await storage_service.save_upload(tenant_id, file)

        if size_bytes > settings.max_file_size_bytes:
            storage_service.delete_file(relative_path)
            raise FileTooLargeError(f"File exceeds max size of {settings.MAX_FILE_SIZE_MB} MB")

        # Check for duplicates in the same tenant
        existing = await self._db.execute(
            select(Document).where(
                Document.tenant_id == tenant_id, Document.checksum == checksum
            )
        )
        if existing.scalar_one_or_none():
            storage_service.delete_file(relative_path)
            # Throw standard ValueError which we can map to 409 Conflict in the router
            raise ValueError("A document with this identical content already exists.")

        doc = Document(
            tenant_id=tenant_id,
            uploaded_by_id=user_id,
            filename=file.filename or "unknown",
            original_filename=file.filename or "unknown",
            mime_type=mime_type,
            file_size_bytes=size_bytes,
            storage_path=relative_path,
            checksum=checksum,
            status="pending",
        )
        self._db.add(doc)
        await self._db.flush()
        return doc

    async def get_by_id(self, document_id: uuid.UUID, tenant_id: uuid.UUID) -> Document:
        result = await self._db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundError("Document", str(document_id))
        if doc.tenant_id != tenant_id:
            raise TenantMismatchError()
        return doc

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Document], int]:
        count_stmt = select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
        stmt = select(Document).where(Document.tenant_id == tenant_id)

        if user_id is not None:
            count_stmt = count_stmt.where(Document.uploaded_by_id == user_id)
            stmt = stmt.where(Document.uploaded_by_id == user_id)

        count_result = await self._db.execute(count_stmt)
        total = count_result.scalar_one()

        result = await self._db.execute(
            stmt.offset(skip).limit(limit).order_by(Document.created_at.desc())
        )
        return list(result.scalars().all()), total

    async def delete(self, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        doc = await self.get_by_id(document_id, tenant_id)
        storage_service.delete_file(doc.storage_path)
        await self._db.delete(doc)
        await self._db.flush()
