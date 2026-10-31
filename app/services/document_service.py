"""
Document service — upload, status, list, delete.

Ingestion (parsing, chunking, embedding) is handled asynchronously by the
Celery worker (app/workers/document_tasks.py).  This service only manages
the metadata lifecycle.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    FileTooLargeError,
    NotFoundError,
    TenantMismatchError,
    UnsupportedFileTypeError,
)
from app.models.document import ALLOWED_MIME_TYPES, Document


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save_upload(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> Document:
        """
        Validate and persist the file, create the Document row.

        The Celery task is dispatched by the router AFTER this returns.
        """
        if mime_type not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileTypeError(
                f"File type {mime_type!r} not supported. Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            )

        if len(content) > settings.max_file_size_bytes:
            raise FileTooLargeError(f"File exceeds max size of {settings.MAX_FILE_SIZE_MB} MB")

        checksum = hashlib.sha256(content).hexdigest()

        # Store file
        storage_path = await self._store_file(tenant_id, checksum, filename, content)

        doc = Document(
            tenant_id=tenant_id,
            uploaded_by_id=user_id,
            filename=Path(storage_path).name,
            original_filename=filename,
            mime_type=mime_type,
            file_size_bytes=len(content),
            storage_path=storage_path,
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
        self, tenant_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> list[Document]:
        result = await self._db.execute(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .offset(skip)
            .limit(limit)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete(self, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        doc = await self.get_by_id(document_id, tenant_id)
        await self._db.delete(doc)
        await self._db.flush()

    # ── Storage helpers ───────────────────────────────────────────────────────

    async def _store_file(
        self,
        tenant_id: uuid.UUID,
        checksum: str,
        original_filename: str,
        content: bytes,
    ) -> str:
        """Write file to local storage. Returns relative path."""
        suffix = Path(original_filename).suffix
        rel_path = f"{tenant_id}/{checksum}{suffix}"
        abs_path = Path(settings.LOCAL_STORAGE_PATH) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(abs_path, "wb") as f:
            await f.write(content)

        return rel_path
