"""
FastAPI dependency injection factories.

Centralising all ``Depends()`` here means:
1. Routers stay thin — they don't import security logic directly.
2. Changing auth strategy (e.g., switching from JWT to session) requires
   changing exactly one file.
3. Easy to override in tests with ``app.dependency_overrides``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token, hash_api_key

# Re-export for routers
DBSession = Annotated[AsyncSession, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


# ── Token extraction ─────────────────────────────────────────────────────────


async def get_current_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    token: str | None = None,
) -> dict:
    """
    Extract and validate auth credentials from either:
    - ``Authorization: Bearer <jwt>`` header, OR
    - ``token`` query parameter (for direct file viewing/downloading), OR
    - ``X-API-Key: adp_...`` header

    Returns the decoded JWT payload dict.
    """
    if credentials:
        # JWT path from Authorization header
        return decode_token(credentials.credentials)

    if token:
        # JWT path from URL query param (e.g. for opening documents in new browser tabs)
        return decode_token(token)

    if api_key:
        # API key path — return a minimal payload; service layer does DB lookup
        return {"sub": None, "tid": None, "roles": [], "api_key_hash": hash_api_key(api_key)}

    raise AuthenticationError("No authentication credentials provided")


TokenPayload = Annotated[dict, Depends(get_current_token_payload)]


# ── Current user ──────────────────────────────────────────────────────────────


class CurrentUser:
    """Resolved user from auth token, injected into route handlers."""

    def __init__(self, user_id: uuid.UUID, tenant_id: uuid.UUID, roles: list[str]) -> None:
        self.id = user_id
        self.tenant_id = tenant_id
        self.roles = roles

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_tenant_admin(self) -> bool:
        return "tenant_admin" in self.roles


async def get_current_user(
    payload: TokenPayload,
    db: DBSession,
) -> CurrentUser:
    """
    Resolve the authenticated user from the JWT payload.

    Raises ``AuthenticationError`` if the user no longer exists or is disabled.
    """
    from app.services.auth_service import AuthService  # Avoid circular imports

    user_id_raw = payload.get("sub")
    tenant_id_raw = payload.get("tid")

    if not user_id_raw or not tenant_id_raw:
        raise AuthenticationError("Malformed token: missing sub or tid")

    try:
        user_id = uuid.UUID(user_id_raw)
        tenant_id = uuid.UUID(tenant_id_raw)
    except ValueError as exc:
        raise AuthenticationError("Malformed token: invalid UUID") from exc

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user or not user.is_active:
        raise AuthenticationError("User account not found or deactivated")

    if user.tenant_id != tenant_id:
        raise AuthenticationError("Token tenant mismatch")

    return CurrentUser(
        user_id=user.id,
        tenant_id=user.tenant_id,
        roles=user.roles,
    )


AuthUser = Annotated[CurrentUser, Depends(get_current_user)]


# ── Role guards ───────────────────────────────────────────────────────────────


def require_role(*roles: str):
    """
    Dependency factory that enforces role membership.

    Usage::

        @router.delete("/tenants/{id}", dependencies=[Depends(require_role("admin"))])
        async def delete_tenant(...): ...
    """

    async def _check(user: AuthUser) -> CurrentUser:
        if not any(r in user.roles for r in roles):
            raise PermissionDeniedError(f"requires role: {' or '.join(roles)}")
        return user

    return Depends(_check)
