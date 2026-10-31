"""
Models package — imports all ORM models so Alembic auto-detects them.

IMPORTANT: Every new model file MUST be imported here, otherwise Alembic
``--autogenerate`` will not see it and will not create the migration.
"""

from app.models.api_key import APIKey
from app.models.base import Base, TimestampMixin, new_uuid
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.query_log import QueryLog
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "new_uuid",
    "Tenant",
    "User",
    "Document",
    "DocumentChunk",
    "QueryLog",
    "APIKey",
]
