"""
Middleware: Request logging with structlog contextvars.

Adds request ID, method, path, status code, and latency to every log line
emitted during request processing — no need to manually pass context around.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Per-request structured logging middleware.

    Injects a ``request_id`` into structlog's context vars, so every log
    line emitted within the request includes it automatically.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Bind context for the duration of this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Attach request_id to response headers (useful for support tickets)
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_exception")
            raise
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "request_completed",
                status_code=getattr(response, "status_code", 500),
                latency_ms=latency_ms,
            )

        response.headers["X-Request-ID"] = request_id
        return response
