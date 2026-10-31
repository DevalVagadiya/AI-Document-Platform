"""
Security utilities: JWT (RS256), password hashing, and API key management.

Design decisions:
- RS256 (asymmetric) JWTs: private key signs, public key verifies.
  This allows read-only verification without distributing the private key.
- Short-lived access tokens (15 min) + long-lived refresh tokens (7 days).
- Refresh tokens stored in httpOnly cookies (XSS-safe).
- API keys: random 32-byte hex string, stored as SHA-256 hash in DB.
  The plaintext is shown to the user ONCE on creation.
- bcrypt for passwords via passlib (work factor 12).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError

# ── Password hashing ─────────────────────────────────────────────────────────

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt (work factor 12)."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if the plaintext matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

_ALGORITHM = "RS256"


def _make_claims(
    subject: str,
    token_type: str,
    extra: dict[str, Any],
    expires_delta: timedelta,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sub": subject,
        "typ": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),  # Unique token ID (useful for revocation)
        **extra,
    }


def create_access_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a short-lived RS256 JWT access token.

    The ``sub`` claim holds the user UUID.
    Additional claims: ``tid`` (tenant), ``roles``.
    """
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = _make_claims(
        subject=user_id,
        token_type="access",
        extra={"tid": tenant_id, "roles": roles},
        expires_delta=delta,
    )
    return jwt.encode(claims, settings.JWT_PRIVATE_KEY, algorithm=_ALGORITHM)


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    """Create a long-lived RS256 refresh token (stored in httpOnly cookie)."""
    delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    claims = _make_claims(
        subject=user_id,
        token_type="refresh",
        extra={"tid": tenant_id},
        expires_delta=delta,
    )
    return jwt.encode(claims, settings.JWT_PRIVATE_KEY, algorithm=_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """
    Decode and validate a JWT.

    Raises ``AuthenticationError`` on any failure (expired, wrong type, bad sig).
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_PUBLIC_KEY,
            algorithms=[_ALGORITHM],
        )
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    if payload.get("typ") != expected_type:
        raise AuthenticationError(f"Expected {expected_type!r} token")

    return payload


# ── API Key helpers ───────────────────────────────────────────────────────────

_API_KEY_PREFIX = "adp_"  # Aids identification in logs / rotation scripts


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.

    Returns:
        plaintext: the full key shown to the user once (``adp_<32 random hex bytes>``).
        hashed:    SHA-256 hex digest stored in the database.
    """
    raw = secrets.token_hex(32)
    plaintext = f"{_API_KEY_PREFIX}{raw}"
    hashed = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, hashed


def hash_api_key(plaintext: str) -> str:
    """Return the SHA-256 digest of a plaintext API key (for lookup in DB)."""
    return hashlib.sha256(plaintext.encode()).hexdigest()
