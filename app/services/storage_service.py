import hashlib
import os
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    """
    Handles physical file storage for documents.
    Currently implements local storage. Can be extended to S3.
    """

    def __init__(self):
        self.storage_path = Path(settings.LOCAL_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, tenant_id: uuid.UUID, upload_file: UploadFile) -> tuple[str, str, int]:
        """
        Saves the uploaded file to disk and computes its SHA-256 checksum and size.
        Returns (relative_storage_path, checksum_hex, size_bytes).
        """
        tenant_dir = self.storage_path / str(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # Generate a unique physical filename to prevent collisions within the tenant
        ext = os.path.splitext(upload_file.filename or "")[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        relative_path = f"{tenant_id}/{unique_filename}"
        absolute_path = self.storage_path / relative_path

        hasher = hashlib.sha256()
        size_bytes = 0

        # We can use chunked reading to support large files without OOM
        # upload_file.read() is async if it's a SpooledTemporaryFile
        with open(absolute_path, "wb") as f:
            while True:
                chunk = await upload_file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                size_bytes += len(chunk)

        # Reset the upload file cursor just in case it's needed again
        await upload_file.seek(0)

        return relative_path, hasher.hexdigest(), size_bytes

    def get_absolute_path(self, relative_path: str) -> Path:
        """Returns the full physical path."""
        return self.storage_path / relative_path

    def delete_file(self, relative_path: str) -> bool:
        """
        Deletes the file from storage. Returns True if deleted or didn't exist.
        """
        abs_path = self.get_absolute_path(relative_path)
        try:
            if abs_path.exists():
                abs_path.unlink()
            return True
        except Exception:
            return False


# Singleton instance
storage_service = StorageService()
