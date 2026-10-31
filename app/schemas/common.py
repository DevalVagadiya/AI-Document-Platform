"""
Common Pydantic schemas used across multiple domain areas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class AppBaseModel(BaseModel):
    """Base for all schemas — forbids extra fields and enables ORM mode."""

    model_config = ConfigDict(
        from_attributes=True,  # ORM mode
        populate_by_name=True,  # Allow both alias and field name
        str_strip_whitespace=True,  # Auto-strip leading/trailing spaces
        extra="forbid",  # Reject unknown fields at validation time
    )


class TimestampSchema(AppBaseModel):
    """Mixin that adds created_at / updated_at fields to a response schema."""

    created_at: datetime
    updated_at: datetime


class PaginatedResponse(AppBaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class MessageResponse(AppBaseModel):
    """Simple success message response."""

    message: str


class ErrorResponse(AppBaseModel):
    """Standardised API error payload."""

    error_code: str
    message: str
    detail: dict | None = None
