"""
Integration tests for auth API endpoints.

Uses the full FastAPI app with an in-memory SQLite DB.
All HTTP transport is handled by httpx.AsyncClient via ASGITransport.

Coverage:
- POST /auth/register            201, duplicate email 409, weak password 422
- POST /auth/login               200 + cookie, wrong password 401
- POST /auth/refresh             200 rotates cookie, missing token 401
- POST /auth/logout              204 clears cookie
- GET  /auth/me                  200 returns profile, 401 without token
- PATCH /auth/me/password        204 success, 401 wrong old password
- POST /auth/users/invite        201 admin, 403 member
- GET  /auth/users               200 admin, 403 member
- GET  /auth/users/{id}          200 admin, 403 member, 404 unknown
- PATCH /auth/users/{id}/role    200 admin, 403 member
- PATCH /auth/users/{id}/deactivate 200 admin, 403 member, self-deactivate 403
- POST /auth/api-keys            201 + plaintext key
- GET  /auth/api-keys            200 list
- DELETE /auth/api-keys/{id}     204 revoke, 404 unknown
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

# Fixtures from conftest: client, member_user, admin_user, tenant,
#   member_headers, admin_headers, super_admin_headers

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/auth"
_TENANT_HEADER = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}


# ── Register ──────────────────────────────────────────────────────────────────


class TestRegister:
    async def test_register_success(self, client: AsyncClient, tenant):
        resp = await client.post(
            f"{_BASE}/register",
            json={
                "email": "fresh@example.com",
                "full_name": "Fresh User",
                "password": "Fresh@Pass1!",
            },
            headers=_TENANT_HEADER,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "fresh@example.com"
        assert "id" in data
        assert "password_hash" not in data  # Never exposed

    async def test_register_duplicate_email_returns_409(self, client: AsyncClient, tenant):
        payload = {
            "email": "dup@example.com",
            "full_name": "Dup User",
            "password": "Dup@Pass1!",
        }
        await client.post(f"{_BASE}/register", json=payload, headers=_TENANT_HEADER)
        resp = await client.post(f"{_BASE}/register", json=payload, headers=_TENANT_HEADER)
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "DUPLICATE_EMAIL"

    async def test_register_weak_password_returns_422(self, client: AsyncClient, tenant):
        resp = await client.post(
            f"{_BASE}/register",
            json={"email": "weak@example.com", "full_name": "Weak User", "password": "weakpass"},
            headers=_TENANT_HEADER,
        )
        assert resp.status_code == 422

    async def test_register_invalid_email_returns_422(self, client: AsyncClient, tenant):
        resp = await client.post(
            f"{_BASE}/register",
            json={"email": "not-an-email", "full_name": "Bad Email", "password": "Val@Pass1!"},
            headers=_TENANT_HEADER,
        )
        assert resp.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_login_success_returns_token(self, client: AsyncClient, member_user, tenant):
        resp = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Member@Pass1!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    async def test_login_sets_refresh_cookie(self, client: AsyncClient, member_user, tenant):
        resp = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Member@Pass1!"},
        )
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password_returns_401(self, client: AsyncClient, member_user, tenant):
        resp = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "WrongPass@1!"},
        )
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_CREDENTIALS"

    async def test_login_nonexistent_user_returns_401(self, client: AsyncClient, tenant):
        resp = await client.post(
            f"{_BASE}/login",
            json={"email": "ghost@example.com", "password": "Ghost@Pass1!"},
        )
        assert resp.status_code == 401

    async def test_login_wrong_and_correct_same_error_code(self, client: AsyncClient, tenant):
        """Ensure user enumeration is impossible — same error for wrong pw vs ghost user."""
        r1 = await client.post(
            f"{_BASE}/login",
            json={"email": "ghost@example.com", "password": "Ghost@Pass1!"},
        )
        r2 = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Wrong@Pass1!"},
        )
        # Both must be 401 with the same error_code
        assert r1.status_code == r2.status_code == 401
        assert r1.json()["error_code"] == r2.json()["error_code"] == "INVALID_CREDENTIALS"


# ── Refresh ───────────────────────────────────────────────────────────────────


class TestRefresh:
    async def test_refresh_with_cookie(self, client: AsyncClient, member_user, tenant):
        # Login to get refresh cookie
        login_resp = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Member@Pass1!"},
        )
        assert login_resp.status_code == 200

        # Refresh using cookie
        refresh_resp = await client.post(f"{_BASE}/refresh")
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" in data

    async def test_refresh_with_body(self, client: AsyncClient, member_user, tenant):
        login_resp = await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Member@Pass1!"},
        )
        refresh_token = login_resp.cookies.get("refresh_token")

        refresh_resp = await client.post(
            f"{_BASE}/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200

    async def test_refresh_missing_token_returns_401(self, client: AsyncClient):
        resp = await client.post(f"{_BASE}/refresh")
        assert resp.status_code == 401

    async def test_refresh_invalid_token_returns_401(self, client: AsyncClient):
        resp = await client.post(
            f"{_BASE}/refresh",
            json={"refresh_token": "invalid.token.here"},
        )
        assert resp.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────


class TestLogout:
    async def test_logout_returns_204(self, client: AsyncClient):
        resp = await client.post(f"{_BASE}/logout")
        assert resp.status_code == 204

    async def test_logout_clears_cookie(self, client: AsyncClient, member_user, tenant):
        await client.post(
            f"{_BASE}/login",
            json={"email": "member@acme.com", "password": "Member@Pass1!"},
        )
        logout_resp = await client.post(f"{_BASE}/logout")
        # After logout the refresh_token cookie should not be set
        assert "refresh_token" not in logout_resp.cookies or \
               logout_resp.cookies["refresh_token"] == ""


# ── /me ───────────────────────────────────────────────────────────────────────


class TestGetMe:
    async def test_get_me_returns_profile(
        self, client: AsyncClient, member_user, member_headers
    ):
        resp = await client.get(f"{_BASE}/me", headers=member_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "member@acme.com"
        assert data["roles"] == ["member"]

    async def test_get_me_without_token_returns_401(self, client: AsyncClient):
        resp = await client.get(f"{_BASE}/me")
        assert resp.status_code == 401

    async def test_get_me_with_invalid_token_returns_401(self, client: AsyncClient):
        resp = await client.get(
            f"{_BASE}/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401


# ── Change own password ───────────────────────────────────────────────────────


class TestChangePassword:
    async def test_change_password_success(
        self, client: AsyncClient, member_user, member_headers
    ):
        resp = await client.patch(
            f"{_BASE}/me/password",
            json={
                "current_password": "Member@Pass1!",
                "new_password": "NewMember@2!",
            },
            headers=member_headers,
        )
        assert resp.status_code == 204

    async def test_change_password_wrong_old(
        self, client: AsyncClient, member_user, member_headers
    ):
        resp = await client.patch(
            f"{_BASE}/me/password",
            json={
                "current_password": "Wrong@Old1!",
                "new_password": "New@Pass1!",
            },
            headers=member_headers,
        )
        assert resp.status_code == 401

    async def test_change_password_requires_auth(self, client: AsyncClient):
        resp = await client.patch(
            f"{_BASE}/me/password",
            json={"current_password": "Old@Pass1!", "new_password": "New@Pass1!"},
        )
        assert resp.status_code == 401


# ── User management (admin only) ──────────────────────────────────────────────


class TestInviteUser:
    async def test_admin_can_invite(
        self, client: AsyncClient, admin_user, admin_headers, tenant
    ):
        resp = await client.post(
            f"{_BASE}/users/invite",
            json={
                "email": "invited@acme.com",
                "full_name": "Invited Person",
                "role": "member",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "invited@acme.com"

    async def test_member_cannot_invite(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        resp = await client.post(
            f"{_BASE}/users/invite",
            json={
                "email": "blocked@acme.com",
                "full_name": "Blocked",
                "role": "member",
            },
            headers=member_headers,
        )
        assert resp.status_code == 403


class TestListUsers:
    async def test_admin_can_list_users(
        self, client: AsyncClient, admin_user, admin_headers, member_user, tenant
    ):
        resp = await client.get(f"{_BASE}/users", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        emails = [u["email"] for u in resp.json()]
        assert "member@acme.com" in emails

    async def test_member_cannot_list_users(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        resp = await client.get(f"{_BASE}/users", headers=member_headers)
        assert resp.status_code == 403

    async def test_unauthenticated_cannot_list_users(self, client: AsyncClient):
        resp = await client.get(f"{_BASE}/users")
        assert resp.status_code == 401


class TestGetUser:
    async def test_admin_can_get_user(
        self, client: AsyncClient, admin_user, admin_headers, member_user, tenant
    ):
        resp = await client.get(
            f"{_BASE}/users/{member_user.id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "member@acme.com"

    async def test_admin_get_nonexistent_user_returns_404(
        self, client: AsyncClient, admin_user, admin_headers, tenant
    ):
        resp = await client.get(
            f"{_BASE}/users/{uuid.uuid4()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_member_cannot_get_other_user(
        self, client: AsyncClient, member_user, member_headers, admin_user, tenant
    ):
        resp = await client.get(
            f"{_BASE}/users/{admin_user.id}",
            headers=member_headers,
        )
        assert resp.status_code == 403


class TestUpdateRole:
    async def test_admin_can_update_role(
        self, client: AsyncClient, admin_user, admin_headers, member_user, tenant
    ):
        resp = await client.patch(
            f"{_BASE}/users/{member_user.id}/role",
            json={"roles": ["tenant_admin"]},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "tenant_admin" in resp.json()["roles"]

    async def test_member_cannot_update_role(
        self, client: AsyncClient, member_user, member_headers, admin_user, tenant
    ):
        resp = await client.patch(
            f"{_BASE}/users/{admin_user.id}/role",
            json={"roles": ["member"]},
            headers=member_headers,
        )
        assert resp.status_code == 403

    async def test_tenant_admin_cannot_grant_super_admin(
        self, client: AsyncClient, admin_user, admin_headers, member_user, tenant
    ):
        """tenant_admin must not be able to escalate to admin."""
        resp = await client.patch(
            f"{_BASE}/users/{member_user.id}/role",
            json={"roles": ["admin"]},
            headers=admin_headers,
        )
        assert resp.status_code == 403


class TestDeactivateUser:
    async def test_admin_can_deactivate(
        self, client: AsyncClient, admin_user, admin_headers, member_user, tenant
    ):
        resp = await client.patch(
            f"{_BASE}/users/{member_user.id}/deactivate",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_member_cannot_deactivate(
        self, client: AsyncClient, member_user, member_headers, admin_user, tenant
    ):
        resp = await client.patch(
            f"{_BASE}/users/{admin_user.id}/deactivate",
            headers=member_headers,
        )
        assert resp.status_code == 403

    async def test_cannot_self_deactivate(
        self, client: AsyncClient, admin_user, admin_headers, tenant
    ):
        resp = await client.patch(
            f"{_BASE}/users/{admin_user.id}/deactivate",
            headers=admin_headers,
        )
        assert resp.status_code == 403


# ── API Keys ──────────────────────────────────────────────────────────────────


class TestAPIKeys:
    async def test_create_api_key(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        resp = await client.post(
            f"{_BASE}/api-keys",
            json={"name": "My CI Key", "description": "Used in CI pipeline"},
            headers=member_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "plaintext_key" in data
        assert data["plaintext_key"].startswith("adp_")
        assert "id" in data
        assert data["is_active"] is True

    async def test_create_api_key_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{_BASE}/api-keys",
            json={"name": "key"},
        )
        assert resp.status_code == 401

    async def test_list_api_keys(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        # Create one first
        await client.post(
            f"{_BASE}/api-keys",
            json={"name": "List Test Key"},
            headers=member_headers,
        )
        resp = await client.get(f"{_BASE}/api-keys", headers=member_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    async def test_revoke_api_key(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        # Create
        create_resp = await client.post(
            f"{_BASE}/api-keys",
            json={"name": "To Revoke"},
            headers=member_headers,
        )
        key_id = create_resp.json()["id"]

        # Revoke
        revoke_resp = await client.delete(
            f"{_BASE}/api-keys/{key_id}",
            headers=member_headers,
        )
        assert revoke_resp.status_code == 204

    async def test_revoke_nonexistent_key_returns_404(
        self, client: AsyncClient, member_user, member_headers, tenant
    ):
        resp = await client.delete(
            f"{_BASE}/api-keys/{uuid.uuid4()}",
            headers=member_headers,
        )
        assert resp.status_code == 404

    async def test_cannot_revoke_other_users_key(
        self, client: AsyncClient,
        member_user, member_headers,
        admin_user, admin_headers,
        tenant,
    ):
        # Admin creates a key
        create_resp = await client.post(
            f"{_BASE}/api-keys",
            json={"name": "Admin Key"},
            headers=admin_headers,
        )
        admin_key_id = create_resp.json()["id"]

        # Member tries to revoke admin's key
        resp = await client.delete(
            f"{_BASE}/api-keys/{admin_key_id}",
            headers=member_headers,
        )
        assert resp.status_code == 404  # Not visible to other users = 404
