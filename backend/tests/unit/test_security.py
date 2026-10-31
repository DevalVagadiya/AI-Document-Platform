"""
Unit tests for app/core/security.py

Tests cover:
- Password hashing (bcrypt): hash format, verify correct/wrong, uniqueness
- JWT: access token creation, refresh token creation, decode, wrong type,
  expired token, tampered signature
- API key: format, deterministic hash, uniqueness
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from jose import JWTError

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_returns_bcrypt_format(self):
        h = hash_password("MyP@ssw0rd!")
        assert h.startswith("$2b$12$"), "Expected bcrypt $2b$ hash with work factor 12"

    def test_verify_correct_password(self):
        h = hash_password("MyP@ssw0rd!")
        assert verify_password("MyP@ssw0rd!", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("MyP@ssw0rd!")
        assert verify_password("WrongPassword", h) is False

    def test_verify_empty_password(self):
        h = hash_password("MyP@ssw0rd!")
        assert verify_password("", h) is False

    def test_hashes_are_unique_per_call(self):
        """bcrypt salts each hash — same plaintext must produce different digests."""
        h1 = hash_password("SamePassword1!")
        h2 = hash_password("SamePassword1!")
        assert h1 != h2

    def test_verify_handles_invalid_hash(self):
        """verify_password must not raise on garbage input — return False."""
        result = verify_password("anypassword", "not-a-valid-hash")
        assert result is False

    def test_unicode_password(self):
        pw = "Pässwórd@1"
        h = hash_password(pw)
        assert verify_password(pw, h) is True


# ── JWT — Access tokens ───────────────────────────────────────────────────────


class TestAccessToken:
    def test_creates_valid_token(self):
        token = create_access_token(
            user_id="user-uuid-123",
            tenant_id="tenant-uuid-456",
            roles=["member"],
        )
        assert isinstance(token, str)
        assert len(token) > 50

    def test_decode_access_token_payload(self):
        user_id = "user-uuid-abc"
        tenant_id = "tenant-uuid-def"
        roles = ["admin", "member"]

        token = create_access_token(user_id=user_id, tenant_id=tenant_id, roles=roles)
        payload = decode_token(token, expected_type="access")

        assert payload["sub"] == user_id
        assert payload["tid"] == tenant_id
        assert payload["roles"] == roles
        assert payload["typ"] == "access"

    def test_access_token_has_jti(self):
        """Each token must have a unique jti claim for revocation."""
        t1 = create_access_token("u1", "t1", ["member"])
        t2 = create_access_token("u1", "t1", ["member"])
        p1 = decode_token(t1)
        p2 = decode_token(t2)
        assert p1["jti"] != p2["jti"]

    def test_access_token_wrong_type_raises(self):
        """Using an access token where refresh is expected must raise."""
        token = create_access_token("uid", "tid", ["member"])
        with pytest.raises(AuthenticationError, match="Expected 'refresh' token"):
            decode_token(token, expected_type="refresh")

    def test_expired_access_token_raises(self):
        token = create_access_token(
            user_id="uid",
            tenant_id="tid",
            roles=["member"],
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        with pytest.raises(AuthenticationError):
            decode_token(token)

    def test_tampered_token_raises(self):
        token = create_access_token("uid", "tid", ["member"])
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthenticationError):
            decode_token(tampered)

    def test_garbage_token_raises(self):
        with pytest.raises(AuthenticationError):
            decode_token("not.a.jwt")

    def test_custom_expiry(self):
        """Custom expires_delta must be respected."""
        token = create_access_token(
            "uid", "tid", ["member"],
            expires_delta=timedelta(hours=2),
        )
        payload = decode_token(token)
        # exp should be approximately 2 hours from now
        from datetime import UTC, datetime
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        now = datetime.now(UTC)
        delta_seconds = (exp - now).total_seconds()
        assert 7100 < delta_seconds < 7300, f"Expected ~7200s, got {delta_seconds}"


# ── JWT — Refresh tokens ──────────────────────────────────────────────────────


class TestRefreshToken:
    def test_creates_refresh_token(self):
        token = create_refresh_token("uid", "tid")
        assert isinstance(token, str)

    def test_decode_refresh_token(self):
        token = create_refresh_token("uid-123", "tid-456")
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "uid-123"
        assert payload["tid"] == "tid-456"
        assert payload["typ"] == "refresh"

    def test_refresh_token_has_no_roles(self):
        """Refresh tokens must NOT embed roles (only access tokens do)."""
        token = create_refresh_token("uid", "tid")
        payload = decode_token(token, expected_type="refresh")
        assert "roles" not in payload

    def test_refresh_used_as_access_raises(self):
        token = create_refresh_token("uid", "tid")
        with pytest.raises(AuthenticationError, match="Expected 'access' token"):
            decode_token(token, expected_type="access")


# ── API Keys ──────────────────────────────────────────────────────────────────


class TestAPIKey:
    def test_generate_api_key_format(self):
        plaintext, hashed = generate_api_key()
        assert plaintext.startswith("adp_"), f"Expected adp_ prefix, got {plaintext[:10]}"
        assert len(hashed) == 64, "Expected SHA-256 hex digest (64 chars)"

    def test_hash_is_deterministic(self):
        plaintext, hashed = generate_api_key()
        assert hash_api_key(plaintext) == hashed

    def test_keys_are_unique(self):
        k1, _ = generate_api_key()
        k2, _ = generate_api_key()
        assert k1 != k2

    def test_different_plaintexts_different_hashes(self):
        _, h1 = generate_api_key()
        _, h2 = generate_api_key()
        assert h1 != h2

    def test_hash_api_key_is_sha256(self):
        import hashlib
        plaintext, stored_hash = generate_api_key()
        expected = hashlib.sha256(plaintext.encode()).hexdigest()
        assert hash_api_key(plaintext) == expected
