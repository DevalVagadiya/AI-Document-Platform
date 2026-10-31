"""
FastAPI application factory.

Using the factory pattern (create_app()) makes it easy to:
- Create the app in tests with different settings
- Reuse the same factory for multiple ASGI apps (e.g., admin vs. public)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.middleware.logging import RequestLoggingMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Startup: configure logging, verify DB connection.
    Shutdown: gracefully close the DB connection pool.
    """
    configure_logging()
    logger.info("startup", app=settings.APP_NAME, env=settings.ENVIRONMENT)

    # Warm up the DB pool
    from app.core.database import _get_engine
    from sqlalchemy import text

    async with _get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database_connected")

    yield

    # Shutdown: dispose the engine (closes all pooled connections)
    await _get_engine().dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Called by uvicorn: ``uvicorn app.main:app``
    """
    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "Production-grade multi-tenant AI Document Intelligence SaaS. "
            "Upload documents, ask questions, get AI-powered answers."
        ),
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware (applied in reverse order — last added = outermost) ─────
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # ── Exception handlers ─────────────────────────────────────────────────
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            error_code=exc.error_code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": exc.error_code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    # ── Routes ─────────────────────────────────────────────────────────────
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    return app


# Module-level app instance — used by uvicorn and tests
app = create_app()
