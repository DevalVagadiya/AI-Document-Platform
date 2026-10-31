"""
V1 API aggregate router.

Imports all sub-routers and registers them under /api/v1.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, documents, health, queries, tenants

router = APIRouter()

router.include_router(health.router)
router.include_router(auth.router)
router.include_router(tenants.router)
router.include_router(documents.router)
router.include_router(queries.router)
