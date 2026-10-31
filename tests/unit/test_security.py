"""
Unit tests for app/core/security.py
"""

from __future__ import annotations

from app.core.security import (
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)

# ── Password tests ────────────────────────────────────────────────────────────


def test_hash_password_returns_bcrypt_string():
    h = hash_password("SuperSecret1")
    assert h.startswith("$2b$")


def test_verify_password_correct():
    h = hash_password("SuperSecret1")
    assert verify_password("SuperSecret1", h) is True


def test_verify_password_wrong():
    h = hash_password("SuperSecret1")
    assert verify_password("WrongPassword", h) is False


def test_hash_is_unique():
    """Same password should produce different hashes (bcrypt salt)."""
    h1 = hash_password("SamePassword1")
    h2 = hash_password("SamePassword1")
    assert h1 != h2


# ── API Key tests ─────────────────────────────────────────────────────────────


def test_generate_api_key_format():
    plaintext, hashed = generate_api_key()
    assert plaintext.startswith("adp_")
    assert len(plaintext) > 10
    assert len(hashed) == 64  # SHA-256 hex


def test_api_key_hash_is_deterministic():
    plaintext, hashed = generate_api_key()
    assert hash_api_key(plaintext) == hashed


def test_api_keys_are_unique():
    key1, _ = generate_api_key()
    key2, _ = generate_api_key()
    assert key1 != key2
