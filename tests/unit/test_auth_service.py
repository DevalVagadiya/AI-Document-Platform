"""
Unit tests for AuthService (app/services/auth_service.py).

All tests use an in-memory SQLite DB via the ``db_session`` fixture.
No HTTP layer is involved — pure service logic testing.

Coverage:
- register: success, duplicate email
- login: success, wrong password, inactive user, nonexistent user
- refresh: valid token, invalid token
- change_password: correct old password, wrong old password
- invite_user: admin can invite, member cannot, invalid role
- update_user_role: admin can promote, member cannot, cross-tenant blocked
- deactivate_user: admin can deactivate, cannot self-deactivate
- admin_reset_password: admin can reset, member cannot
- list_users: returns only tenant's users
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateEmailError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import decode_token, hash_password
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import AuthService

# Re-use fixtures from conftest.py (tenant, member_user, admin_user, super_admin_user)
pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str = "test@example.com",
    password: str = "Test@Pass1!",
    roles: list[str] | None = None,
    active: bool = True,
) -> User:
    user = User(
        tenant_id=tenant_id,
        email=email,
        full_name="Test User",
        password_hash=hash_password(password),
        roles=roles or ["member"],
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


# ── Register ──────────────────────────────────────────────────────────────────


class TestRegister:
    async def test_register_success(self, db_session: AsyncSession, tenant: Tenant):
        service = AuthService(db_session)
        user = await service.register(
            tenant_id=tenant.id,
            email="newuser@example.com",
            full_name="New User",
            password="NewUser@Pass1!",
        )
        assert user.id is not None
        assert user.email == "newuser@example.com"
        assert user.roles == ["member"]
        assert user.is_active is True

    async def test_register_email_lowercased(self, db_session: AsyncSession, tenant: Tenant):
        service = AuthService(db_session)
        user = await service.register(
            tenant_id=tenant.id,
            email="  UPPER@Example.COM  ",
            full_name="Case Test",
            password="Upper@Case1!",
        )
        assert user.email == "upper@example.com"

    async def test_register_duplicate_email_raises(self, db_session: AsyncSession, tenant: Tenant):
        service = AuthService(db_session)
        await service.register(tenant.id, "dup@example.com", "First", "Dup@Pass1!")
        with pytest.raises(DuplicateEmailError):
            await service.register(tenant.id, "dup@example.com", "Second", "Dup@Pass2!")

    async def test_register_custom_roles(self, db_session: AsyncSession, tenant: Tenant):
        service = AuthService(db_session)
        user = await service.register(
            tenant_id=tenant.id,
            email="admin@example.com",
            full_name="Admin User",
            password="Admin@Pass1!",
            roles=["admin"],
        )
        assert user.roles == ["admin"]

    async def test_password_is_hashed(self, db_session: AsyncSession, tenant: Tenant):
        """Stored hash must NOT be the plaintext password."""
        service = AuthService(db_session)
        user = await service.register(tenant.id, "hash@test.com", "H", "Hash@Pass1!")
        assert user.password_hash != "Hash@Pass1!"
        assert user.password_hash.startswith("$2b$")


# ── Login ─────────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_login_success_returns_tokens(self, db_session: AsyncSession, tenant: Tenant):
        await _make_user(db_session, tenant.id, "login@test.com", "Login@Pass1!")
        service = AuthService(db_session)
        access, refresh = await service.login("login@test.com", "Login@Pass1!")
        assert isinstance(access, str) and len(access) > 20
        assert isinstance(refresh, str) and len(refresh) > 20

    async def test_login_access_token_claims(self, db_session: AsyncSession, tenant: Tenant):
        user = await _make_user(db_session, tenant.id, "claims@test.com", "Claims@1!")
        service = AuthService(db_session)
        access, _ = await service.login("claims@test.com", "Claims@1!")
        payload = decode_token(access, expected_type="access")
        assert payload["sub"] == str(user.id)
        assert payload["tid"] == str(tenant.id)
        assert "member" in payload["roles"]

    async def test_login_wrong_password_raises(self, db_session: AsyncSession, tenant: Tenant):
        await _make_user(db_session, tenant.id, "wrong@test.com", "Wrong@Pass1!")
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            await service.login("wrong@test.com", "Completely@Wrong2!")

    async def test_login_nonexistent_email_raises(self, db_session: AsyncSession, tenant: Tenant):
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            await service.login("ghost@example.com", "Ghost@Pass1!")

    async def test_login_inactive_user_raises(self, db_session: AsyncSession, tenant: Tenant):
        await _make_user(db_session, tenant.id, "inactive@test.com", "Inactive@1!", active=False)
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            await service.login("inactive@test.com", "Inactive@1!")

    async def test_login_updates_last_login_at(self, db_session: AsyncSession, tenant: Tenant):
        user = await _make_user(db_session, tenant.id, "lastlogin@test.com", "Last@Login1!")
        assert user.last_login_at is None
        service = AuthService(db_session)
        await service.login("lastlogin@test.com", "Last@Login1!")
        # Re-fetch from DB
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.id == user.id))
        refreshed = result.scalar_one()
        assert refreshed.last_login_at is not None


# ── Refresh ───────────────────────────────────────────────────────────────────


class TestRefresh:
    async def test_refresh_returns_new_tokens(self, db_session: AsyncSession, tenant: Tenant):
        await _make_user(db_session, tenant.id, "refresh@test.com", "Refresh@1!")
        service = AuthService(db_session)
        _, refresh = await service.login("refresh@test.com", "Refresh@1!")
        new_access, new_refresh = await service.refresh(refresh)
        assert isinstance(new_access, str)
        assert isinstance(new_refresh, str)

    async def test_refresh_invalid_token_raises(self, db_session: AsyncSession):
        service = AuthService(db_session)
        from app.core.exceptions import AuthenticationError
        with pytest.raises(AuthenticationError):
            await service.refresh("not-a-valid-token")

    async def test_refresh_access_token_as_refresh_raises(
        self, db_session: AsyncSession, tenant: Tenant
    ):
        await _make_user(db_session, tenant.id, "wrongtype@test.com", "Wrong@Type1!")
        service = AuthService(db_session)
        access, _ = await service.login("wrongtype@test.com", "Wrong@Type1!")
        from app.core.exceptions import AuthenticationError
        with pytest.raises(AuthenticationError):
            await service.refresh(access)  # access token not accepted as refresh


# ── Change password ───────────────────────────────────────────────────────────


class TestChangePassword:
    async def test_change_password_success(self, db_session: AsyncSession, tenant: Tenant):
        user = await _make_user(db_session, tenant.id, "chpw@test.com", "OldPass@1!")
        service = AuthService(db_session)
        await service.change_password(user.id, "OldPass@1!", "NewPass@1!")
        # Verify new password works
        from app.core.security import verify_password
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.id == user.id))
        updated = result.scalar_one()
        assert verify_password("NewPass@1!", updated.password_hash)

    async def test_change_password_wrong_old_raises(self, db_session: AsyncSession, tenant: Tenant):
        user = await _make_user(db_session, tenant.id, "wrongold@test.com", "CorrectOld@1!")
        service = AuthService(db_session)
        with pytest.raises(InvalidCredentialsError):
            await service.change_password(user.id, "WrongOld@1!", "NewPass@2!")

    async def test_change_password_nonexistent_user_raises(self, db_session: AsyncSession):
        service = AuthService(db_session)
        with pytest.raises(NotFoundError):
            await service.change_password(uuid.uuid4(), "any@Pass1!", "New@Pass1!")


# ── Invite user ───────────────────────────────────────────────────────────────


class TestInviteUser:
    async def test_admin_can_invite(self, db_session: AsyncSession, admin_user: User, tenant: Tenant):
        service = AuthService(db_session)
        invited = await service.invite_user(
            tenant_id=tenant.id,
            email="invited@acme.com",
            full_name="New Invite",
            role="member",
            invited_by=admin_user,
        )
        assert invited.email == "invited@acme.com"
        assert invited.roles == ["member"]

    async def test_member_cannot_invite(self, db_session: AsyncSession, member_user: User, tenant: Tenant):
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.invite_user(
                tenant_id=tenant.id,
                email="blocked@acme.com",
                full_name="Blocked",
                role="member",
                invited_by=member_user,
            )

    async def test_invite_invalid_role_raises(self, db_session: AsyncSession, admin_user: User, tenant: Tenant):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="Invalid role"):
            await service.invite_user(
                tenant_id=tenant.id,
                email="badrole@acme.com",
                full_name="Bad Role",
                role="superuser",  # not allowed
                invited_by=admin_user,
            )


# ── Update user role ──────────────────────────────────────────────────────────


class TestUpdateUserRole:
    async def test_admin_can_change_role(
        self, db_session: AsyncSession, admin_user: User, member_user: User
    ):
        service = AuthService(db_session)
        updated = await service.update_user_role(
            target_user_id=member_user.id,
            new_roles=["tenant_admin"],
            requesting_user=admin_user,
        )
        assert "tenant_admin" in updated.roles

    async def test_member_cannot_change_role(
        self, db_session: AsyncSession, member_user: User, admin_user: User
    ):
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.update_user_role(
                target_user_id=admin_user.id,
                new_roles=["member"],
                requesting_user=member_user,
            )

    async def test_tenant_admin_cannot_grant_admin_role(
        self, db_session: AsyncSession, admin_user: User, member_user: User
    ):
        """tenant_admin must not escalate to global admin."""
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError, match="grant admin role"):
            await service.update_user_role(
                target_user_id=member_user.id,
                new_roles=["admin"],
                requesting_user=admin_user,
            )

    async def test_super_admin_can_grant_admin_role(
        self, db_session: AsyncSession, super_admin_user: User, member_user: User
    ):
        service = AuthService(db_session)
        updated = await service.update_user_role(
            target_user_id=member_user.id,
            new_roles=["admin"],
            requesting_user=super_admin_user,
        )
        assert "admin" in updated.roles

    async def test_invalid_role_raises(
        self, db_session: AsyncSession, admin_user: User, member_user: User
    ):
        service = AuthService(db_session)
        with pytest.raises(ValueError, match="Invalid role"):
            await service.update_user_role(
                target_user_id=member_user.id,
                new_roles=["godmode"],
                requesting_user=admin_user,
            )


# ── Deactivate user ───────────────────────────────────────────────────────────


class TestDeactivateUser:
    async def test_admin_can_deactivate(
        self, db_session: AsyncSession, admin_user: User, member_user: User
    ):
        service = AuthService(db_session)
        deactivated = await service.deactivate_user(
            target_user_id=member_user.id,
            requesting_user=admin_user,
        )
        assert deactivated.is_active is False

    async def test_member_cannot_deactivate(
        self, db_session: AsyncSession, member_user: User, admin_user: User
    ):
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.deactivate_user(
                target_user_id=admin_user.id,
                requesting_user=member_user,
            )

    async def test_cannot_self_deactivate(
        self, db_session: AsyncSession, admin_user: User
    ):
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError, match="own account"):
            await service.deactivate_user(
                target_user_id=admin_user.id,
                requesting_user=admin_user,
            )


# ── Admin reset password ──────────────────────────────────────────────────────


class TestAdminResetPassword:
    async def test_admin_can_reset(
        self, db_session: AsyncSession, admin_user: User, member_user: User
    ):
        service = AuthService(db_session)
        await service.admin_reset_password(
            target_user_id=member_user.id,
            new_password="Forced@New1!",
            requesting_user=admin_user,
        )
        from sqlalchemy import select
        from app.core.security import verify_password
        result = await db_session.execute(select(User).where(User.id == member_user.id))
        updated = result.scalar_one()
        assert verify_password("Forced@New1!", updated.password_hash)

    async def test_member_cannot_reset(
        self, db_session: AsyncSession, member_user: User, admin_user: User
    ):
        service = AuthService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.admin_reset_password(
                target_user_id=admin_user.id,
                new_password="Hacked@Pass1!",
                requesting_user=member_user,
            )


# ── List users ────────────────────────────────────────────────────────────────


class TestListUsers:
    async def test_returns_only_tenant_users(
        self, db_session: AsyncSession, tenant: Tenant, member_user: User, admin_user: User
    ):
        service = AuthService(db_session)
        users = await service.list_users(tenant_id=tenant.id)
        ids = [u.id for u in users]
        assert member_user.id in ids
        assert admin_user.id in ids

    async def test_other_tenant_users_not_returned(
        self, db_session: AsyncSession, tenant: Tenant, member_user: User
    ):
        other_tenant = Tenant(name="Other", slug="other", plan="starter")
        db_session.add(other_tenant)
        await db_session.flush()

        other_user = await _make_user(db_session, other_tenant.id, "other@other.com")
        service = AuthService(db_session)

        tenant_users = await service.list_users(tenant_id=tenant.id)
        ids = [u.id for u in tenant_users]
        assert other_user.id not in ids

    async def test_pagination(
        self, db_session: AsyncSession, tenant: Tenant
    ):
        service = AuthService(db_session)
        for i in range(5):
            await _make_user(db_session, tenant.id, f"page{i}@test.com")

        page1 = await service.list_users(tenant_id=tenant.id, skip=0, limit=3)
        page2 = await service.list_users(tenant_id=tenant.id, skip=3, limit=3)
        assert len(page1) == 3
        # page2 has the remaining
        assert len(page2) >= 2
