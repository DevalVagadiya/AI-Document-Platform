"""
Auth-related Pydantic schemas (request / response).
"""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import AppBaseModel, TimestampSchema

# ── Request schemas ───────────────────────────────────────────────────────────


class LoginRequest(AppBaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(AppBaseModel):
    """Used when sending refresh token in the body instead of a cookie."""

    refresh_token: str


class RegisterRequest(AppBaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class CreateAPIKeyRequest(AppBaseModel):
    name: str = Field(min_length=1, max_length=100)


# ── Response schemas ──────────────────────────────────────────────────────────


class TokenResponse(AppBaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds


class UserResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str
    roles: list[str]
    is_active: bool


class APIKeyResponse(TimestampSchema):
    id: uuid.UUID
    name: str
    key_prefix: str  # e.g. "adp_ab12cd34"
    is_active: bool


class APIKeyCreatedResponse(APIKeyResponse):
    """Includes the plaintext key — shown ONCE on creation."""

    plaintext_key: str
