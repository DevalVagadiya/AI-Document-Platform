"""
Custom exception hierarchy for the platform.

Design decisions:
- All domain exceptions inherit from ``AppError`` so FastAPI exception
  handlers can catch the entire family in one place.
- Each exception carries an HTTP status code and a machine-readable ``error_code``
  for consistent API error responses.
- Using separate classes (not a single generic error with a string) makes
  intent explicit and enables type-safe exception handling.
"""

from __future__ import annotations

from http import HTTPStatus


class AppError(Exception):
    """Base class for all application-defined exceptions."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "An unexpected error occurred") -> None:
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(message={self.message!r})"


# ── 400 Bad Request ──────────────────────────────────────────────────────────


class ValidationError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class FileTooLargeError(AppError):
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    error_code = "FILE_TOO_LARGE"


class UnsupportedFileTypeError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "UNSUPPORTED_FILE_TYPE"


# ── 401 Unauthorized ─────────────────────────────────────────────────────────


class AuthenticationError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    error_code = "AUTHENTICATION_ERROR"


class InvalidCredentialsError(AuthenticationError):
    error_code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("Invalid email or password")


class TokenExpiredError(AuthenticationError):
    error_code = "TOKEN_EXPIRED"

    def __init__(self) -> None:
        super().__init__("Token has expired")


# ── 403 Forbidden ─────────────────────────────────────────────────────────────


class PermissionDeniedError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    error_code = "PERMISSION_DENIED"

    def __init__(self, action: str = "perform this action") -> None:
        super().__init__(f"You do not have permission to {action}")


class TenantMismatchError(PermissionDeniedError):
    error_code = "TENANT_MISMATCH"

    def __init__(self) -> None:
        super().__init__("access resources from another tenant")


# ── 404 Not Found ─────────────────────────────────────────────────────────────


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    error_code = "NOT_FOUND"

    def __init__(self, resource: str = "Resource", id: str = "") -> None:
        detail = f"{resource} not found"
        if id:
            detail += f" (id={id!r})"
        super().__init__(detail)


# ── 409 Conflict ──────────────────────────────────────────────────────────────


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    error_code = "CONFLICT"


class DuplicateEmailError(ConflictError):
    error_code = "DUPLICATE_EMAIL"

    def __init__(self) -> None:
        super().__init__("A user with this email already exists")


class DuplicateTenantSlugError(ConflictError):
    error_code = "DUPLICATE_TENANT_SLUG"

    def __init__(self, slug: str) -> None:
        super().__init__(f"Tenant slug {slug!r} is already taken")


# ── 429 Rate Limit ────────────────────────────────────────────────────────────


class RateLimitError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, resource: str = "requests") -> None:
        super().__init__(f"Rate limit exceeded for {resource}")


# ── 503 Service Unavailable ───────────────────────────────────────────────────


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"


class VectorStoreError(ServiceUnavailableError):
    error_code = "VECTOR_STORE_ERROR"


class LLMError(ServiceUnavailableError):
    error_code = "LLM_ERROR"
