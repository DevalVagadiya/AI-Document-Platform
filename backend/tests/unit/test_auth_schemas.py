"""
Unit tests for auth-related Pydantic schemas (app/schemas/auth.py).

Tests cover:
- RegisterRequest: valid data, weak passwords, field validation
- LoginRequest: valid/invalid email, empty password
- ChangePasswordRequest: strength validation on new password
- UpdateUserRoleRequest: valid/invalid roles
- InviteUserRequest: role enum validation
- TokenResponse / UserResponse: serialisation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    ChangePasswordRequest,
    InviteUserRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateUserRoleRequest,
    UserResponse,
)


# ── RegisterRequest ───────────────────────────────────────────────────────────


class TestRegisterRequest:
    def test_valid_registration(self):
        req = RegisterRequest(
            email="user@example.com",
            full_name="John Doe",
            password="Str0ng@Pass!",
        )
        assert req.email == "user@example.com"

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="at least 8"):
            RegisterRequest(email="a@b.com", full_name="X", password="Sh@1!")

    def test_password_no_uppercase(self):
        with pytest.raises(ValidationError, match="uppercase"):
            RegisterRequest(email="a@b.com", full_name="X", password="lower@pass1!")

    def test_password_no_lowercase(self):
        with pytest.raises(ValidationError, match="lowercase"):
            RegisterRequest(email="a@b.com", full_name="X", password="UPPER@PASS1!")

    def test_password_no_digit(self):
        with pytest.raises(ValidationError, match="digit"):
            RegisterRequest(email="a@b.com", full_name="X", password="NoDigit@Pass!")

    def test_password_no_special_char(self):
        with pytest.raises(ValidationError, match="special character"):
            RegisterRequest(email="a@b.com", full_name="X", password="NoSpecialChar1")

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", full_name="X", password="Valid@Pass1!")

    def test_full_name_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@b.com", full_name="X", password="Valid@Pass1!")

    def test_full_name_too_long(self):
        with pytest.raises(ValidationError):
            RegisterRequest(
                email="a@b.com",
                full_name="A" * 256,
                password="Valid@Pass1!",
            )


# ── LoginRequest ──────────────────────────────────────────────────────────────


class TestLoginRequest:
    def test_valid_login(self):
        req = LoginRequest(email="user@example.com", password="anypassword")
        assert req.email == "user@example.com"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="notanemail", password="password")

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com", password="")


# ── ChangePasswordRequest ─────────────────────────────────────────────────────


class TestChangePasswordRequest:
    def test_valid_change(self):
        req = ChangePasswordRequest(
            current_password="OldPass@1!",
            new_password="NewPass@2!",
        )
        assert req.new_password == "NewPass@2!"

    def test_weak_new_password(self):
        with pytest.raises(ValidationError, match="uppercase|digit|lowercase|special"):
            ChangePasswordRequest(
                current_password="OldPass@1!",
                new_password="weakpassword",
            )


# ── UpdateUserRoleRequest ─────────────────────────────────────────────────────


class TestUpdateUserRoleRequest:
    def test_valid_member_role(self):
        req = UpdateUserRoleRequest(roles=["member"])
        assert req.roles == ["member"]

    def test_valid_tenant_admin_role(self):
        req = UpdateUserRoleRequest(roles=["tenant_admin"])
        assert req.roles == ["tenant_admin"]

    def test_valid_admin_role(self):
        req = UpdateUserRoleRequest(roles=["admin"])
        assert req.roles == ["admin"]

    def test_invalid_role_raises(self):
        with pytest.raises(ValidationError, match="Invalid role"):
            UpdateUserRoleRequest(roles=["superuser"])

    def test_empty_roles_raises(self):
        with pytest.raises(ValidationError):
            UpdateUserRoleRequest(roles=[])


# ── InviteUserRequest ─────────────────────────────────────────────────────────


class TestInviteUserRequest:
    def test_valid_invite(self):
        req = InviteUserRequest(
            email="new@example.com",
            full_name="New User",
            role="member",
        )
        assert req.role == "member"

    def test_invalid_role_pattern(self):
        with pytest.raises(ValidationError):
            InviteUserRequest(
                email="new@example.com",
                full_name="New User",
                role="godmode",
            )

    def test_default_role_is_member(self):
        req = InviteUserRequest(email="x@y.com", full_name="Someone")
        assert req.role == "member"


# ── TokenResponse ─────────────────────────────────────────────────────────────


class TestTokenResponse:
    def test_token_response_defaults(self):
        resp = TokenResponse(access_token="abc.def.ghi", expires_in=900)
        assert resp.token_type == "bearer"
        assert resp.expires_in == 900


# ── UserResponse ──────────────────────────────────────────────────────────────


class TestUserResponse:
    def test_from_dict(self):
        resp = UserResponse.model_validate({
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "email": "user@test.com",
            "full_name": "Test User",
            "roles": ["member"],
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        assert resp.is_active is True
        assert "member" in resp.roles
