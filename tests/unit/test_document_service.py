import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.document_service import DocumentService


def create_mock_upload_file(filename: str, content: bytes, content_type: str) -> UploadFile:
    file = io.BytesIO(content)
    upload_file = UploadFile(file=file, filename=filename, size=len(content))
    # Starlette's UploadFile reads content_type from headers
    from starlette.datastructures import Headers
    upload_file.headers = Headers({"content-type": content_type})
    return upload_file


@pytest.mark.asyncio
class TestDocumentService:
    async def test_upload_success(self, db_session: AsyncSession, tenant, member_user):
        service = DocumentService(db_session)
        file = create_mock_upload_file("test.txt", b"hello world", "text/plain")

        doc = await service.save_upload(
            tenant_id=tenant.id,
            user_id=member_user.id,
            file=file,
        )

        assert doc.filename == "test.txt"
        assert doc.mime_type == "text/plain"
        assert doc.file_size_bytes == 11
        assert doc.status == "pending"

    async def test_upload_unsupported_type_raises(self, db_session: AsyncSession, tenant, member_user):
        service = DocumentService(db_session)
        file = create_mock_upload_file("test.exe", b"binary", "application/x-msdownload")

        from app.core.exceptions import UnsupportedFileTypeError
        with pytest.raises(UnsupportedFileTypeError):
            await service.save_upload(tenant_id=tenant.id, user_id=member_user.id, file=file)

    async def test_upload_duplicate_content_raises(self, db_session: AsyncSession, tenant, member_user):
        service = DocumentService(db_session)
        file1 = create_mock_upload_file("test1.txt", b"duplicate content", "text/plain")
        file2 = create_mock_upload_file("test2.txt", b"duplicate content", "text/plain")

        await service.save_upload(tenant_id=tenant.id, user_id=member_user.id, file=file1)

        with pytest.raises(ValueError, match="already exists"):
            await service.save_upload(tenant_id=tenant.id, user_id=member_user.id, file=file2)

    async def test_list_and_get_documents(self, db_session: AsyncSession, tenant, member_user):
        service = DocumentService(db_session)
        file1 = create_mock_upload_file("file1.txt", b"content 1", "text/plain")
        file2 = create_mock_upload_file("file2.txt", b"content 2", "text/plain")

        doc1 = await service.save_upload(tenant.id, member_user.id, file1)
        doc2 = await service.save_upload(tenant.id, member_user.id, file2)

        # Get list
        docs, total = await service.list_for_tenant(tenant.id)
        assert total == 2
        assert len(docs) == 2

        # Get by id
        fetched = await service.get_by_id(doc1.id, tenant.id)
        assert fetched.id == doc1.id

    async def test_delete_document(self, db_session: AsyncSession, tenant, member_user):
        service = DocumentService(db_session)
        file = create_mock_upload_file("del.txt", b"delete me", "text/plain")
        doc = await service.save_upload(tenant.id, member_user.id, file)

        await service.delete(doc.id, tenant.id)

        # Ensure deleted
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await service.get_by_id(doc.id, tenant.id)
