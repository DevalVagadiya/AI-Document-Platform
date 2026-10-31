"""
Authentication API endpoints — clean, thin controller layer.

All business logic lives in ``AuthService``. This router only:
  1. Deserialises the HTTP request into Python objects.
  2. Calls the service method.
  3. Serialises the result back to JSON.
  4. Sets / clears cookies.

Endpoints
---------
POST   /auth/register              Self-service registration
POST   /auth/login                 Email+password → JWT pair
POST   /auth/refresh               Refresh access token via cookie or body
POST   /auth/logout                Clear refresh cookie
GET    /auth/me                    Current user profile
PATCH  /auth/me/password           Self-service password change
POST   /auth/users/invite          Admin: invite a new user
GET    /auth/users                 Admin: list tenant users
GET    /auth/users/{id}            Admin: get any user profile
PATCH  /auth/users/{id}/role       Admin: update user roles
PATCH  /auth/users/{id}/deactivate Admin: deactivate user
POST   /auth/api-keys              Create API key
GET    /auth/api-keys              List API keys
DELETE /auth/api-keys/{id}         Revoke API key
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import AuthUser, require_role
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import generate_api_key
from app.models.api_key import APIKey
from app.schemas.auth import (
    AdminResetPasswordRequest,
    APIKeyCreatedResponse,
    APIKeyResponse,
    ChangePasswordRequest,
    CreateAPIKeyRequest,
    InviteUserRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateUserRoleRequest,
    UserResponse,
    UserSummary,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Cookie configuration ──────────────────────────────────────────────────────

_REFRESH_COOKIE = "refresh_token"
_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days in seconds


def _set_refresh_cookie(response: Response, token: str, *, secure: bool = True) -> None:
    """Set the httpOnly refresh-token cookie."""
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=secure,          # False only in development HTTP
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/api/v1/auth",    # Scoped: only sent to /auth/* endpoints
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path="/api/v1/auth")


# ── Registration & Login ──────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Self-service registration. The tenant context is resolved from the "
        "``X-Tenant-ID`` header. For production, replace with invite-token-based flow."
    ),
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # Tenant resolution: In production, use invite tokens or a subdomain router.
    # For now, accept an optional X-Tenant-ID header (defaults to demo tenant).
    tenant_id_header = request.headers.get("X-Tenant-ID")
    try:
        tenant_id = uuid.UUID(tenant_id_header) if tenant_id_header else uuid.UUID("00000000-0000-0000-0000-000000000001")
    except ValueError:
        from app.core.exceptions import ValidationError
        raise ValidationError("Invalid X-Tenant-ID header")

    service = AuthService(db)
    user = await service.register(
        tenant_id=tenant_id,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description="Returns a short-lived access token. Sets a httpOnly refresh token cookie.",
)
async def login(
    body: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthService(db)
    access_token, refresh_token = await service.login(body.email, body.password)

    # Set refresh token as httpOnly cookie (XSS-safe)
    secure = request.url.scheme == "https"
    _set_refresh_cookie(response, refresh_token, secure=secure)

    from app.core.config import settings
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh the access token",
    description=(
        "Reads the refresh token from the ``refresh_token`` cookie (preferred) "
        "or the ``refresh_token`` query/body field. Returns a new access token "
        "and rotates the refresh token cookie."
    ),
)
async def refresh_token(
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
    cookie_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> TokenResponse:
    # Prefer cookie; fall back to JSON body
    token = cookie_token
    if not token:
        try:
            body = await request.json()
            token = body.get("refresh_token")
        except Exception:
            pass

    if not token:
        raise AuthenticationError("No refresh token provided")

    service = AuthService(db)
    new_access, new_refresh = await service.refresh(token)

    # Rotate: issue a new refresh cookie
    secure = request.url.scheme == "https"
    _set_refresh_cookie(response, new_refresh, secure=secure)

    from app.core.config import settings
    return TokenResponse(
        access_token=new_access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout — clear refresh token cookie",
)
async def logout(response: Response) -> None:
    _clear_refresh_cookie(response)


# ── Current user ──────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = AuthService(db)
    user = await service.get_user_by_id(current_user.id)
    if not user:
        raise AuthenticationError("User not found")
    return UserResponse.model_validate(user)


@router.patch(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your own password",
)
async def change_own_password(
    body: ChangePasswordRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    service = AuthService(db)
    await service.change_password(
        user_id=current_user.id,
        current_password=body.current_password,
        new_password=body.new_password,
    )


# ── User management (admin/tenant_admin only) ─────────────────────────────────

_admin_roles = require_role("admin", "tenant_admin")


@router.post(
    "/users/invite",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new user (Admin)",
    dependencies=[_admin_roles],
)
async def invite_user(
    body: InviteUserRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = AuthService(db)
    # Resolve full requesting user object for role checks inside service
    requester = await service.get_user_by_id(current_user.id)
    if not requester:
        raise AuthenticationError("Requester not found")

    user = await service.invite_user(
        tenant_id=current_user.tenant_id,
        email=body.email,
        full_name=body.full_name,
        role=body.role,
        invited_by=requester,
    )
    return UserResponse.model_validate(user)


@router.get(
    "/users",
    response_model=list[UserSummary],
    summary="List all users in the tenant (Admin)",
    dependencies=[_admin_roles],
)
async def list_users(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
) -> list[UserSummary]:
    service = AuthService(db)
    users = await service.list_users(
        tenant_id=current_user.tenant_id,
        skip=skip,
        limit=min(limit, 200),
    )
    return [UserSummary.model_validate(u) for u in users]


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Get a specific user (Admin)",
    dependencies=[_admin_roles],
)
async def get_user(
    user_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = AuthService(db)
    user = await service.get_user_by_id(user_id)
    if not user or user.tenant_id != current_user.tenant_id:
        raise NotFoundError("User", str(user_id))
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Update a user's roles (Admin)",
    dependencies=[_admin_roles],
)
async def update_user_role(
    user_id: uuid.UUID,
    body: UpdateUserRoleRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = AuthService(db)
    requester = await service.get_user_by_id(current_user.id)
    if not requester:
        raise AuthenticationError("Requester not found")

    user = await service.update_user_role(
        target_user_id=user_id,
        new_roles=body.roles,
        requesting_user=requester,
    )
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate a user account (Admin)",
    dependencies=[_admin_roles],
)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = AuthService(db)
    requester = await service.get_user_by_id(current_user.id)
    if not requester:
        raise AuthenticationError("Requester not found")

    user = await service.deactivate_user(
        target_user_id=user_id,
        requesting_user=requester,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/users/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: reset a user's password",
    dependencies=[_admin_roles],
)
async def admin_reset_password(
    user_id: uuid.UUID,
    body: AdminResetPasswordRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    service = AuthService(db)
    requester = await service.get_user_by_id(current_user.id)
    if not requester:
        raise AuthenticationError("Requester not found")

    await service.admin_reset_password(
        target_user_id=user_id,
        new_password=body.new_password,
        requesting_user=requester,
    )


# ── API Keys ──────────────────────────────────────────────────────────────────


@router.post(
    "/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
    description="Generates a new API key. The plaintext key is returned ONCE — store it securely.",
)
async def create_api_key(
    body: CreateAPIKeyRequest,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    plaintext, hashed = generate_api_key()

    api_key = APIKey(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        key_hash=hashed,
        key_prefix=plaintext[:16],  # Store prefix for display (safe)
    )
    db.add(api_key)
    await db.flush()

    response_data = APIKeyResponse.model_validate(api_key)
    return APIKeyCreatedResponse(
        **response_data.model_dump(),
        plaintext_key=plaintext,
    )


@router.get(
    "/api-keys",
    response_model=list[APIKeyResponse],
    summary="List your API keys",
)
async def list_api_keys(
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyResponse]:
    from sqlalchemy import select
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user.id)
        .order_by(APIKey.created_at.desc())
    )
    return [APIKeyResponse.model_validate(k) for k in result.scalars().all()]


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: AuthUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    from sqlalchemy import select
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.user_id == current_user.id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise NotFoundError("APIKey", str(key_id))
    key.is_active = False
