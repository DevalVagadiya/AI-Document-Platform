"""
Authentication API endpoints.

POST /auth/register   — create a new user (admin or self-service)
POST /auth/login      — get access token + set refresh cookie
POST /auth/refresh    — issue new access token using refresh token
POST /auth/logout     — clear refresh cookie
GET  /auth/me         — current user profile
POST /auth/api-keys   — create a new API key
GET  /auth/api-keys   — list API keys
DELETE /auth/api-keys/{id} — revoke API key
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import AuthUser
from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, decode_token, generate_api_key
from app.models.api_key import APIKey
from app.schemas.auth import (
    APIKeyCreatedResponse,
    APIKeyResponse,
    CreateAPIKeyRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])

_REFRESH_COOKIE = "refresh_token"
_COOKIE_OPTS = {
    "httponly": True,
    "secure": True,
    "samesite": "lax",
    "max_age": 7 * 24 * 3600,
}


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Self-service registration. The first user in a new tenant should be
    provisioned via the admin ``/tenants`` endpoint. This endpoint assumes
    the tenant_id is embedded in the request or resolved from an invite token.

    For bootstrap purposes it creates a user under a fixed demo tenant.
    """
    # TODO: resolve tenant from invite token / header
    demo_tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    service = AuthService(db)
    user = await service.register(
        tenant_id=demo_tenant_id,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return JWT access token. Refresh token set in cookie."""
    service = AuthService(db)
    access_token, refresh_token = await service.login(body.email, body.password)

    # Set refresh token as httpOnly cookie
    response.set_cookie(_REFRESH_COOKIE, refresh_token, **_COOKIE_OPTS)  # type: ignore[arg-type]

    from app.core.config import settings

    return TokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    refresh_token: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Issue new access token using the refresh token from cookie.
    """
    if not refresh_token:
        raise AuthenticationError("No refresh token provided")

    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = payload["sub"]
    _ = payload["tid"]  # Validated but not directly used here

    service = AuthService(db)
    user = await service.get_user_by_id(uuid.UUID(user_id))
    if not user or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    new_access = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        roles=user.roles,
    )
    from app.core.config import settings

    return TokenResponse(
        access_token=new_access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(_REFRESH_COOKIE)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    service = AuthService(db)
    user = await service.get_user_by_id(current_user.id)
    if not user:
        raise AuthenticationError("User not found")
    return UserResponse.model_validate(user)


@router.post("/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: CreateAPIKeyRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    """Generate and store a new API key. Plaintext is returned ONCE."""
    plaintext, hashed = generate_api_key()

    api_key = APIKey(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=body.name,
        key_hash=hashed,
        key_prefix=plaintext[:16],
    )
    db.add(api_key)
    await db.flush()

    response = APIKeyCreatedResponse.model_validate(api_key)
    response = response.model_copy(update={"plaintext_key": plaintext})
    return response


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyResponse]:
    """List all API keys for the current user."""
    from sqlalchemy import select

    result = await db.execute(
        select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc())
    )
    return [APIKeyResponse.model_validate(k) for k in result.scalars().all()]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke (deactivate) an API key."""
    from sqlalchemy import select

    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("APIKey", str(key_id))
    key.is_active = False
