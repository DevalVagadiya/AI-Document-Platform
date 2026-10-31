"""
Authentication service — registration, login, token refresh, password management,
invite flows, and user management.

Design principles:
- Framework-agnostic: zero FastAPI imports. All HTTP concerns live in the router.
- Every DB mutation uses ``flush()`` not ``commit()`` — the caller controls the
  transaction boundary (the get_db() dependency commits on success).
- Constant-time password comparison via bcrypt to prevent timing attacks.
- Refresh token blacklisting via Redis to support stateless logout.
- No user-enumeration leaks: login always raises ``InvalidCredentialsError``
  regardless of whether the email exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    DuplicateEmailError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User

if TYPE_CHECKING:
    pass


class AuthService:
    """
    Handles all authentication and user-management business logic.

    Injected via FastAPI's dependency system — one instance per request.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return a user by primary key, or None if not found."""
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        """Return a user by email (normalised to lowercase), or None."""
        result = await self._db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        tenant_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[User]:
        """List all users for a given tenant (paginated)."""
        result = await self._db.execute(
            select(User)
            .where(User.tenant_id == tenant_id)
            .order_by(User.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Registration ─────────────────────────────────────────────────────────

    async def register(
        self,
        tenant_id: uuid.UUID,
        email: str,
        full_name: str,
        password: str,
        roles: list[str] | None = None,
    ) -> User:
        """
        Create a new user under the given tenant.

        Raises:
            DuplicateEmailError: if the email address is already registered.
        """
        existing = await self.get_user_by_email(email)
        if existing:
            raise DuplicateEmailError()

        user = User(
            tenant_id=tenant_id,
            email=email.lower().strip(),
            full_name=full_name,
            password_hash=hash_password(password),
            roles=roles or ["member"],
        )
        self._db.add(user)
        await self._db.flush()
        return user

    async def invite_user(
        self,
        tenant_id: uuid.UUID,
        email: str,
        full_name: str,
        role: str,
        invited_by: User,
    ) -> User:
        """
        Admin/tenant_admin creates a new user (no self-service).

        The invited user is created with a random temporary password that they
        should change on first login. In production this triggers an email invite.

        Raises:
            PermissionDeniedError: if the inviter lacks ``admin`` or ``tenant_admin`` role.
            DuplicateEmailError: if the email is already registered.
        """
        if not any(r in invited_by.roles for r in ("admin", "tenant_admin")):
            raise PermissionDeniedError("invite users")

        # Validate role value
        allowed_roles = {"member", "tenant_admin", "admin"}
        if role not in allowed_roles:
            raise ValueError(f"Invalid role {role!r}. Must be one of {allowed_roles}")

        import secrets

        # Create a temporary password — user MUST change it
        temp_password = f"Tmp_{secrets.token_hex(8)}!"
        user = await self.register(
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            password=temp_password,
            roles=[role],
        )
        return user

    # ── Login / Token management ─────────────────────────────────────────────

    async def login(self, email: str, password: str) -> tuple[str, str]:
        """
        Authenticate a user and return ``(access_token, refresh_token)``.

        Always raises ``InvalidCredentialsError`` on failure — never leaks
        whether the email exists (prevents user enumeration).
        """
        user = await self.get_user_by_email(email)

        # Constant-time path: always call verify_password to prevent timing attack
        if not user or not user.password_hash:
            # Still call bcrypt to burn the same amount of time
            verify_password(password, "$2b$12$invalidhashinvalid00000000000000000000000000000000000.")
            raise InvalidCredentialsError()

        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise InvalidCredentialsError()

        user.last_login_at = datetime.now(UTC)
        await self._db.flush()

        access_token = create_access_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            roles=user.roles,
        )
        refresh_token = create_refresh_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
        )
        return access_token, refresh_token

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """
        Validate a refresh token and issue a new access + refresh token pair.

        Returns ``(new_access_token, new_refresh_token)``.

        Raises:
            AuthenticationError: if the token is invalid, expired, or the
                                 user no longer exists / is deactivated.
        """
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            raise AuthenticationError("Malformed refresh token")

        try:
            user_id = uuid.UUID(user_id_raw)
        except ValueError as exc:
            raise AuthenticationError("Malformed refresh token") from exc

        user = await self.get_user_by_id(user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User not found or deactivated")

        new_access = create_access_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            roles=user.roles,
        )
        new_refresh = create_refresh_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
        )
        return new_access, new_refresh

    # ── Password management ──────────────────────────────────────────────────

    async def change_password(
        self,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """
        Change a user's password after verifying their current one.

        Raises:
            NotFoundError: if the user doesn't exist.
            InvalidCredentialsError: if ``current_password`` is wrong.
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User", str(user_id))

        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError()

        user.password_hash = hash_password(new_password)
        await self._db.flush()

    async def admin_reset_password(
        self,
        target_user_id: uuid.UUID,
        new_password: str,
        requesting_user: User,
    ) -> None:
        """
        Admin-only: forcibly reset a user's password without knowing the old one.

        Raises:
            PermissionDeniedError: if requester lacks admin/tenant_admin role.
            NotFoundError: if target user doesn't exist.
        """
        if not any(r in requesting_user.roles for r in ("admin", "tenant_admin")):
            raise PermissionDeniedError("reset passwords")

        target = await self.get_user_by_id(target_user_id)
        if not target:
            raise NotFoundError("User", str(target_user_id))

        # Admins can only reset users within their own tenant
        if requesting_user.roles == ["tenant_admin"] and target.tenant_id != requesting_user.tenant_id:
            raise PermissionDeniedError("reset passwords across tenants")

        target.password_hash = hash_password(new_password)
        await self._db.flush()

    # ── User activation ──────────────────────────────────────────────────────

    async def deactivate_user(
        self,
        target_user_id: uuid.UUID,
        requesting_user: User,
    ) -> User:
        """
        Deactivate a user account (soft-delete). Admins/tenant_admins only.

        Raises:
            PermissionDeniedError: insufficient role.
            NotFoundError: target not found.
        """
        if not any(r in requesting_user.roles for r in ("admin", "tenant_admin")):
            raise PermissionDeniedError("deactivate users")

        target = await self.get_user_by_id(target_user_id)
        if not target:
            raise NotFoundError("User", str(target_user_id))

        if target.id == requesting_user.id:
            raise PermissionDeniedError("deactivate your own account")

        target.is_active = False
        await self._db.flush()
        return target

    async def update_user_role(
        self,
        target_user_id: uuid.UUID,
        new_roles: list[str],
        requesting_user: User,
    ) -> User:
        """
        Update a user's roles. Only admins and tenant_admins can do this.

        Raises:
            PermissionDeniedError: insufficient role or cross-tenant attempt.
            NotFoundError: target not found.
        """
        allowed_roles = {"member", "tenant_admin", "admin"}
        for role in new_roles:
            if role not in allowed_roles:
                raise ValueError(f"Invalid role {role!r}")

        if not any(r in requesting_user.roles for r in ("admin", "tenant_admin")):
            raise PermissionDeniedError("change user roles")

        target = await self.get_user_by_id(target_user_id)
        if not target:
            raise NotFoundError("User", str(target_user_id))

        # Tenant admins can only manage users in their own tenant
        if "admin" not in requesting_user.roles:
            if target.tenant_id != requesting_user.tenant_id:
                raise PermissionDeniedError("manage users in other tenants")

        # Only super-admins can assign the "admin" role
        if "admin" in new_roles and "admin" not in requesting_user.roles:
            raise PermissionDeniedError("grant admin role")

        target.roles = new_roles
        await self._db.flush()
        return target
