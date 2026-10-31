"""
Alembic environment configuration — async-ready.

Key design decisions:
1. Uses asyncpg (async) for migrations via ``run_async_migrations()``.
2. Imports ``app.models`` so all ORM models are registered with ``Base.metadata``
   before autogenerate runs.
3. ``include_schemas = True`` enables schema-level migration support.
4. The sync URL is derived from the async URL by swapping the driver.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Import all models so Alembic can detect them ──────────────────────────────
import app.models  # noqa: F401 — side-effect: registers all models with Base.metadata
from app.core.database import Base
from app.core.config import settings

# Alembic Config object from alembic.ini
config = context.config

# Configure Python logging from alembic.ini's [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic compares against the database
target_metadata = Base.metadata

# Override the sqlalchemy.url from alembic.ini with the value from settings
# (avoids duplicating the DB URL in alembic.ini)
config.set_main_option("sqlalchemy.url", settings.database_url_sync)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (without a live DB connection).

    Generates a SQL script that can be reviewed and applied manually.
    Useful for production environments where the migration is applied by a DBA.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using the async engine (for production use)."""
    # Build the async engine from alembic.ini + our async URL
    async_url = str(settings.DATABASE_URL)
    connectable = async_engine_from_config(
        {"sqlalchemy.url": async_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no connection pooling during migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations (normal mode)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
