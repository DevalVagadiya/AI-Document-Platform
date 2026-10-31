"""
Auth-related Pydantic v2 schemas (request / response).

Design decisions:
- ``AppBaseModel`` enforces ``model_config = ConfigDict(from_attributes=True)``
  so ORM models can be validated directly via ``model_validate(orm_obj)``.
- Passwords are validated for strength at the schema layer (not service layer)
  so validation errors return clean 422 responses with field-level detail.
- Response schemas never include ``password_hash`` — ever.
- ``UserResponse`` and ``UserSummary`` are distinct: ``UserSummary`` is for list
  endpoints where callers don't need every field.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import AppBaseModel, TimestampSchema


# ── Validators ────────────────────────────────────────────────────────────────

_PASSWORD_MIN_LEN = 8
_PASSWORD_MAX_LEN = 128


def _validate_password_strength(v: str) -> str:
    """Shared password strength validator used by multiple schemas."""
    if len(v) < _PASSWORD_MIN_LEN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LEN} characters")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()-_=+[]{}|;:',.<>?/`~" for c in v):
        raise ValueError("Password must contain at least one special character")
    return v


# ── Request schemas ───────────────────────────────────────────────────────────


class LoginRequest(AppBaseModel):
    """Credentials for email/password login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX_LEN)


class RegisterRequest(AppBaseModel):
    """
    Self-service account creation.

    ``tenant_id`` is resolved by the router (from an invite token or the
    authenticated user's tenant context) — not supplied by the client.
    """

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=_PASSWORD_MIN_LEN, max_length=_PASSWORD_MAX_LEN)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class InviteUserRequest(AppBaseModel):
    """Admin-initiated user creation (generates a temporary password)."""

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    role: str = Field(default="member", pattern="^(member|tenant_admin|admin)$")


class ChangePasswordRequest(AppBaseModel):
    """Self-service password change — requires current password for verification."""

    current_password: str = Field(min_length=1, max_length=_PASSWORD_MAX_LEN)
    new_password: str = Field(min_length=_PASSWORD_MIN_LEN, max_length=_PASSWORD_MAX_LEN)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class AdminResetPasswordRequest(AppBaseModel):
    """Admin resets a user's password without knowing the old one."""

    new_password: str = Field(min_length=_PASSWORD_MIN_LEN, max_length=_PASSWORD_MAX_LEN)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class UpdateUserRoleRequest(AppBaseModel):
    """Update one or more roles on a user account."""

    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        allowed = {"member", "tenant_admin", "admin"}
        for role in v:
            if role not in allowed:
                raise ValueError(f"Invalid role {role!r}. Allowed: {allowed}")
        return v


class RefreshRequest(AppBaseModel):
    """Used when sending refresh token in the body instead of a cookie."""

    refresh_token: str


class CreateAPIKeyRequest(AppBaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


# ── Response schemas ──────────────────────────────────────────────────────────


class TokenResponse(AppBaseModel):
    """Returned on login and token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expiry


class TokenPairResponse(TokenResponse):
    """Returned when both tokens are sent in the body (non-cookie mode)."""

    refresh_token: str


class UserResponse(TimestampSchema):
    """Full user profile — returned on /me and /users/{id}."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str
    roles: list[str]
    is_active: bool
    last_login_at: datetime | None = None


class UserSummary(AppBaseModel):
    """Compact user representation for list endpoints."""

    id: uuid.UUID
    email: EmailStr
    full_name: str
    roles: list[str]
    is_active: bool


class APIKeyResponse(TimestampSchema):
    """API key metadata (no secret)."""

    id: uuid.UUID
    name: str
    description: str = ""
    key_prefix: str  # e.g. "adp_ab12cd34..."
    is_active: bool
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class APIKeyCreatedResponse(APIKeyResponse):
    """
    Returned on API key creation — includes the plaintext key.

    The client MUST store this securely. It will NOT be shown again.
    """

    plaintext_key: str
