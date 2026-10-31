"""
Tenant-related Pydantic schemas.
"""

from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.schemas.common import AppBaseModel, TimestampSchema


class TenantCreate(AppBaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    plan: str = Field(default="starter")

    @field_validator("slug")
    @classmethod
    def slug_lowercase(cls, v: str) -> str:
        return v.lower()


class TenantUpdate(AppBaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    plan: str | None = None
    is_active: bool | None = None


class TenantResponse(TimestampSchema):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
