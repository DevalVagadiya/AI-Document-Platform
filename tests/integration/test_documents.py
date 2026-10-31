import pytest
from httpx import AsyncClient

_BASE = "/api/v1"


@pytest.mark.asyncio
class TestDocuments:
    async def test_upload_document_success(self, client: AsyncClient, member_headers):
        files = {"file": ("test.txt", b"Hello World!", "text/plain")}
        resp = await client.post(f"{_BASE}/documents", files=files, headers=member_headers)
        
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "test.txt"
        assert data["status"] == "pending"

    async def test_upload_invalid_mime_type_returns_415(self, client: AsyncClient, member_headers):
        files = {"file": ("test.exe", b"binary", "application/octet-stream")}
        resp = await client.post(f"{_BASE}/documents", files=files, headers=member_headers)
        
        assert resp.status_code == 415

    async def test_upload_duplicate_content_returns_409(self, client: AsyncClient, member_headers):
        files1 = {"file": ("dup1.txt", b"duplicate content", "text/plain")}
        files2 = {"file": ("dup2.txt", b"duplicate content", "text/plain")}
        
        resp1 = await client.post(f"{_BASE}/documents", files=files1, headers=member_headers)
        assert resp1.status_code == 201
        
        resp2 = await client.post(f"{_BASE}/documents", files=files2, headers=member_headers)
        assert resp2.status_code == 409

    async def test_list_documents(self, client: AsyncClient, member_headers):
        files = {"file": ("list1.txt", b"list content", "text/plain")}
        await client.post(f"{_BASE}/documents", files=files, headers=member_headers)
        
        resp = await client.get(f"{_BASE}/documents", headers=member_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1

    async def test_get_document(self, client: AsyncClient, member_headers):
        files = {"file": ("get1.txt", b"get content", "text/plain")}
        upload_resp = await client.post(f"{_BASE}/documents", files=files, headers=member_headers)
        doc_id = upload_resp.json()["id"]

        resp = await client.get(f"{_BASE}/documents/{doc_id}", headers=member_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == doc_id

    async def test_delete_document(self, client: AsyncClient, member_headers):
        files = {"file": ("del1.txt", b"delete content", "text/plain")}
        upload_resp = await client.post(f"{_BASE}/documents", files=files, headers=member_headers)
        doc_id = upload_resp.json()["id"]

        del_resp = await client.delete(f"{_BASE}/documents/{doc_id}", headers=member_headers)
        assert del_resp.status_code == 204

        get_resp = await client.get(f"{_BASE}/documents/{doc_id}", headers=member_headers)
        assert get_resp.status_code == 404
