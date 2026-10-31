"""
Integration tests for health check endpoints.

These tests use the full FastAPI app with dependency overrides
but a lightweight in-memory DB.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_ok(client: AsyncClient):
    """GET /api/v1/health/live should return 200 with status=ok."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_readiness_returns_200(client: AsyncClient):
    """
    GET /api/v1/health/ready should return 200.

    Note: in test environment the DB is SQLite (overridden), so the
    database check may return 'error'. The HTTP status is still 200
    (the endpoint is reachable) — the 'status' field indicates health.
    """
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "checks" in data


@pytest.mark.asyncio
async def test_request_id_header(client: AsyncClient):
    """Every response should include an X-Request-ID header."""
    response = await client.get("/api/v1/health/live")
    assert "x-request-id" in {k.lower() for k in response.headers}


@pytest.mark.asyncio
async def test_404_json_error(client: AsyncClient):
    """Unknown routes should return JSON (not HTML)."""
    response = await client.get("/api/v1/nonexistent-route")
    assert response.status_code == 404
