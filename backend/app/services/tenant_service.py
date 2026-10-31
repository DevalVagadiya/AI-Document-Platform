"""
Tenant service — CRUD operations for tenants.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateTenantSlugError, NotFoundError
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantUpdate


class TenantService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, data: TenantCreate) -> Tenant:
        existing = await self._db.execute(select(Tenant).where(Tenant.slug == data.slug))
        if existing.scalar_one_or_none():
            raise DuplicateTenantSlugError(data.slug)

        tenant = Tenant(**data.model_dump())
        self._db.add(tenant)
        await self._db.flush()
        return tenant

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise NotFoundError("Tenant", str(tenant_id))
        return tenant

    async def list_all(self, skip: int = 0, limit: int = 50) -> list[Tenant]:
        result = await self._db.execute(
            select(Tenant).offset(skip).limit(limit).order_by(Tenant.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, tenant_id: uuid.UUID, data: TenantUpdate) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(tenant, field, value)
        await self._db.flush()
        return tenant

    async def delete(self, tenant_id: uuid.UUID) -> None:
        tenant = await self.get_by_id(tenant_id)
        await self._db.delete(tenant)
        await self._db.flush()
