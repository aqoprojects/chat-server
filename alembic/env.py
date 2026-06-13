from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from alembic import context

# ── Load app config and models ────────────────────────────────────────────────
# These imports trigger model registration into Base.metadata.
from core.config import settings
from db.base import Base
import db.models  # noqa: F401 — side effect: registers all Table objects

# ── Alembic Config object (wraps alembic.ini) ─────────────────────────────────
config = context.config

# ── Python logging — use the same config as the app ──────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

    # ── Target metadata — Alembic compares this against the live DB ───────────────
    target_metadata = Base.metadata


    # ══════════════════════════════════════════════════════════════════════════════
    #  Offline mode — generate SQL without connecting to the DB
    #  Usage: alembic upgrade head --sql
    # ══════════════════════════════════════════════════════════════════════════════

def run_migrations_offline() -> None:
    """
    Emit migration SQL to stdout without a live DB connection.
    Useful for reviewing what will be executed before applying.
    """
    context.configure(
        url=str(settings.database_sync_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include schemas so cross-schema foreign keys are handled.
        include_schemas=True,
        # Render AS INTEGER for server_default integer values.
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


        # ══════════════════════════════════════════════════════════════════════════════
        #  Online mode — connect and run migrations
        #  Usage: alembic upgrade head
        # ══════════════════════════════════════════════════════════════════════════════

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # compare_type=True: detect column type changes (e.g. VARCHAR(50) →
        # VARCHAR(100)) and generate ALTER COLUMN statements.
        compare_type=True,
        # compare_server_default=True: detect changes to server-side
        # default values and generate ALTER COLUMN statements.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create a synchronous connection from the sync engine and pass it
    to Alembic. Alembic does not support asyncpg directly — it needs
    a DBAPI-2 compatible connection, which psycopg2 provides.
    """
from db.session import get_sync_engine

sync_engine = get_sync_engine()

with sync_engine.connect() as connection:
    do_run_migrations(connection)

    sync_engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


    # ── Entry point ────────────────────────────────────────────────────────────────
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()