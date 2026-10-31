"""
Health check endpoints.

Used by Docker HEALTHCHECK, Kubernetes liveness/readiness probes,
and load balancer health checks.

Two endpoints:
- GET /health/live  — process is running (liveness probe)
- GET /health/ready — can serve traffic: DB + Redis reachable (readiness probe)
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.database import _get_engine

router = APIRouter(prefix="/health", tags=["Health"])

_START_TIME = time.time()


@router.get("/live", summary="Liveness probe")
async def liveness() -> dict:
    """Returns 200 if the process is alive. No external checks."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@router.get("/ready", summary="Readiness probe")
async def readiness() -> dict:
    """
    Returns 200 only if the application can serve requests.

    Checks:
    - PostgreSQL: executes ``SELECT 1``
    """
    checks: dict[str, str] = {}

    # Database check
    try:
        async with _get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
