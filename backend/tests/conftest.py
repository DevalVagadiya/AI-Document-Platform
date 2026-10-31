"""
Pytest configuration and shared fixtures for auth tests.

Design:
- Real RSA-2048 keypair generated once per session (fast, ~10ms).
- Settings patched before any app import to avoid ValidationError.
- In-memory SQLite via aiosqlite for zero-infra test isolation.
- Each test gets a fresh schema via ``db_session`` fixture.
- ``client`` fixture overrides ``get_db`` so all HTTP calls hit the test DB.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Generate RSA keys for tests ───────────────────────────────────────────────
# Done at module level so it runs once per test session.

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_public_pem = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

# ── Patch env BEFORE importing app modules ────────────────────────────────────

os.environ["APP_NAME"] = "Test App"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-exactly-32chars"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["JWT_PRIVATE_KEY"] = _private_pem.replace("\n", "\\n")
os.environ["JWT_PUBLIC_KEY"] = _public_pem.replace("\n", "\\n")
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ENVIRONMENT"] = "development"

# Now safe to import app modules
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core.security import hash_password, create_access_token  # noqa: E402

# ── Settings override ─────────────────────────────────────────────────────────


def override_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


# ── Async test infra ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── In-memory SQLite DB ───────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Isolated SQLite in-memory database per test.

    SQLite doesn't support all PostgreSQL types (e.g., UUID, ARRAY).
    We use JSON for roles and CHAR for UUIDs (SQLite compatible).
    StaticPool ensures all connections share the same in-memory DB.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Common data fixtures ──────────────────────────────────────────────────────

_DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture()
async def tenant(db_session: AsyncSession) -> Tenant:
    """Create and persist a test tenant."""
    t = Tenant(
        id=_DEMO_TENANT_ID,
        name="Acme Corp",
        slug="acme",
        plan="starter",
    )
    db_session.add(t)
    await db_session.flush()
    return t


@pytest_asyncio.fixture()
async def member_user(db_session: AsyncSession, tenant: Tenant) -> User:
    """A regular member user in the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="member@acme.com",
        full_name="Alice Member",
        password_hash=hash_password("Member@Pass1!"),
        roles=["member"],
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture()
async def admin_user(db_session: AsyncSession, tenant: Tenant) -> User:
    """A tenant_admin user in the test tenant."""
    user = User(
        tenant_id=tenant.id,
        email="admin@acme.com",
        full_name="Bob Admin",
        password_hash=hash_password("Admin@Pass1!"),
        roles=["tenant_admin"],
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture()
async def super_admin_user(db_session: AsyncSession, tenant: Tenant) -> User:
    """A super-admin user (admin role)."""
    user = User(
        tenant_id=tenant.id,
        email="superadmin@acme.com",
        full_name="Charlie Super",
        password_hash=hash_password("Super@Pass1!"),
        roles=["admin"],
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ── HTTP test client ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def test_app(db_session: AsyncSession) -> FastAPI:
    app = create_app()

    async def _override_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest_asyncio.fixture()
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Auth header helpers ───────────────────────────────────────────────────────


def make_auth_headers(user: User) -> dict[str, str]:
    """Return Authorization headers for the given user."""
    token = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        roles=user.roles,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture()
async def member_headers(member_user: User) -> dict[str, str]:
    return make_auth_headers(member_user)


@pytest_asyncio.fixture()
async def admin_headers(admin_user: User) -> dict[str, str]:
    return make_auth_headers(admin_user)


@pytest_asyncio.fixture()
async def super_admin_headers(super_admin_user: User) -> dict[str, str]:
    return make_auth_headers(super_admin_user)
