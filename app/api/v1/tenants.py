"""
Tenants API endpoints (admin only).

POST   /tenants/         — create tenant
GET    /tenants/         — list all tenants
GET    /tenants/{id}     — get tenant
PATCH  /tenants/{id}     — update tenant
DELETE /tenants/{id}     — delete tenant
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate
from app.services.tenant_service import TenantService

router = APIRouter(
    prefix="/tenants",
    tags=["Tenants"],
    dependencies=[require_role("admin")],  # All endpoints require admin role
)


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Create a new tenant. Requires global admin role."""
    service = TenantService(db)
    tenant = await service.create(body)
    return TenantResponse.model_validate(tenant)


@router.get("/", response_model=list[TenantResponse])
async def list_tenants(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[TenantResponse]:
    """List all tenants (admin only)."""
    service = TenantService(db)
    tenants = await service.list_all(skip=skip, limit=limit)
    return [TenantResponse.model_validate(t) for t in tenants]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    service = TenantService(db)
    return TenantResponse.model_validate(await service.get_by_id(tenant_id))


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    service = TenantService(db)
    tenant = await service.update(tenant_id, body)
    return TenantResponse.model_validate(tenant)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    service = TenantService(db)
    await service.delete(tenant_id)
