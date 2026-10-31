"""
Authentication service — user registration, login, token refresh.

All DB operations go through the injected AsyncSession.
This service is intentionally framework-agnostic: no FastAPI imports.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateEmailError,
    InvalidCredentialsError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User


class AuthService:
    """Handles user auth business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def register(
        self,
        tenant_id: uuid.UUID,
        email: str,
        full_name: str,
        password: str,
        roles: list[str] | None = None,
    ) -> User:
        """Create a new user. Raises DuplicateEmailError if email taken."""
        existing = await self.get_user_by_email(email)
        if existing:
            raise DuplicateEmailError()

        user = User(
            tenant_id=tenant_id,
            email=email.lower(),
            full_name=full_name,
            password_hash=hash_password(password),
            roles=roles or ["member"],
        )
        self._db.add(user)
        await self._db.flush()  # Get the generated ID before commit
        return user

    async def login(self, email: str, password: str) -> tuple[str, str]:
        """
        Authenticate a user and return (access_token, refresh_token).

        Raises InvalidCredentialsError on failure to avoid user enumeration.
        """
        user = await self.get_user_by_email(email)
        if not user or not user.password_hash:
            raise InvalidCredentialsError()

        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise InvalidCredentialsError()

        # Update last login (best-effort)
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
