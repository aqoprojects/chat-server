from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level singletons
#  Both are None until init_db_engine() is called from lifespan.py
# ══════════════════════════════════════════════════════════════════════════════

_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


# ══════════════════════════════════════════════════════════════════════════════
#  Engine initialisation (called once from lifespan.py on startup)
# ══════════════════════════════════════════════════════════════════════════════


async def init_db_engine() -> None:
    """
    Create the async SQLAlchemy engine and session factory.
    Stores both in module-level variables so all subsequent calls
    to get_db() and async_session_factory() use the same pool.

    Pool settings come from core.config.settings so they can be
    tuned per environment without touching this file.
    """
    global _engine, _async_session_factory

    if _engine is not None:
        # Already initialised — guard against accidental double-call
        log.warning("db_engine_already_initialised")
        return

    _engine = create_async_engine(
        str(settings.database_url),
        # ── Connection pool ───────────────────────────────────────────────
        # pool_size: number of persistent connections kept open.
        # max_overflow: extra connections allowed above pool_size
        #               when all pool connections are busy.
        # Total max connections = pool_size + max_overflow.
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # pool_timeout: seconds to wait for a connection from the pool
        # before raising TimeoutError.
        pool_timeout=settings.db_pool_timeout,
        # pool_recycle: seconds after which a connection is replaced.
        # Prevents "connection already closed" errors caused by
        # PostgreSQL's idle connection timeout or firewalls killing
        # long-lived idle connections.
        pool_recycle=settings.db_pool_recycle,
        # pool_pre_ping: before handing a connection to the application,
        # issue a cheap "SELECT 1" to verify it is still alive.
        # Silently replaces dead connections instead of raising errors.
        pool_pre_ping=True,
        # echo: log every SQL statement. True in development only.
        # Reads db_echo_sql from the environment-specific settings class.
        echo=getattr(settings, "db_echo_sql", False),
        # connect_args: passed directly to asyncpg.
        # command_timeout: max seconds for any single DB operation.
        # server_settings: PostgreSQL session-level settings applied
        #   on every new connection.
        connect_args={
            "command_timeout": 60,
            "server_settings": {
                # Tag all connections from this app so pg_stat_activity
                # shows them as "chatserver" instead of just "asyncpg".
                "application_name": "chatserver",
                # Enforce UTC for all timestamp operations.
                # Without this, timestamp comparisons can silently produce
                # wrong results if the DB server is in a different timezone.
                "timezone": "UTC",
            },
        },
    )

    # ── Attach a checkout listener for per-connection setup ───────────────────
    # This listener fires each time a connection is checked out of the pool.
    # We use it to set a statement timeout so runaway queries can never
    # hold a connection indefinitely.
    @event.listens_for(_engine.sync_engine, "connect")
    def set_connection_defaults(
        dbapi_connection: object, connection_record: object
    ) -> None:
        # asyncpg exposes the underlying psycopg-like connection here.
        # We use the raw connection to run SET commands that apply for
        # the lifetime of this connection.
        pass  # Timeouts are set via command_timeout in connect_args above.

    # ── Session factory ───────────────────────────────────────────────────────
    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        # expire_on_commit=False: after session.commit(), ORM objects
        # remain usable without triggering a lazy-load (which would fail
        # in an async context anyway). Routes can safely return committed
        # objects to Pydantic for serialization.
        expire_on_commit=False,
        # autobegin=True (default): a transaction begins implicitly on
        # the first database operation. We always commit or rollback
        # explicitly — we never rely on autocommit.
        autobegin=True,
        # autoflush=False: do not flush pending changes to the DB before
        # every query. We flush manually where needed. This prevents
        # confusing implicit writes in complex multi-step service functions.
        autoflush=False,
    )

    log.info(
        "db_engine_created",
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        host=settings.postgres_host,
        db=settings.postgres_db,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Engine teardown (called from lifespan.py on shutdown)
# ══════════════════════════════════════════════════════════════════════════════


async def close_db_engine() -> None:
    """
    Dispose the async engine — closes all pooled connections gracefully.
    Called from lifespan.py during shutdown.
    """
    global _engine, _async_session_factory

    if _engine is None:
        return

    await _engine.dispose()
    _engine = None
    _async_session_factory = None

    log.info("db_engine_disposed")

    # ══════════════════════════════════════════════════════════════════════════════
    #  Public accessors
    # ══════════════════════════════════════════════════════════════════════════════


def get_engine() -> AsyncEngine:
    """
    Return the module-level engine.
    Raises RuntimeError if called before init_db_engine().
    """
    if _engine is None:
        raise RuntimeError(
            "Database engine has not been initialised. "
            "Ensure init_db_engine() is called during application startup."
        )
    return _engine


def async_session_factory() -> AsyncSession:
    """
    Return a new AsyncSession from the session factory.
    Used by lifespan.py for the startup connectivity check and by
    scripts that need a session outside a request context.

    For request-scoped sessions use the get_db() dependency instead.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Session factory has not been initialised. "
            "Ensure init_db_engine() is called during application startup."
        )
    return _async_session_factory()

    # ══════════════════════════════════════════════════════════════════════════════
    #  FastAPI dependency — request-scoped session
    # ══════════════════════════════════════════════════════════════════════════════


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
        FastAPI dependency that yields one AsyncSession per request.

        Usage in a route:
    from db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

            @router.get("/example")
            async def example(db: AsyncSession = Depends(get_db)):
                result = await db.execute(select(User))
                ...

                Transaction behaviour:
                    - A transaction begins implicitly on the first DB operation
                    (autobegin=True on the session factory).
                    - The route or service function must call await db.commit()
                    to persist changes.
                    - If an exception propagates out of the route, the session
                    is rolled back automatically in the finally block below.
                    - The session is always closed (returned to the pool) in the
                finally block, regardless of success or failure.

                Why not auto-commit here:
                    Auto-committing in the dependency would silently commit partial
                    writes if a service function raises after some writes succeed.
                    Explicit commits in service functions make transaction boundaries
                    visible and intentional.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Session factory is not initialised. "
            "The application lifespan may not have run yet."
        )

    async with _async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # ══════════════════════════════════════════════════════════════════════════════
    #  Utility — get a raw async connection for advanced operations
    # ══════════════════════════════════════════════════════════════════════════════

    async def get_raw_connection() -> AsyncGenerator[AsyncConnection, None]:
        """
        Yield a raw AsyncConnection from the engine pool.

        Use this ONLY for operations that cannot go through the ORM:
            - COPY FROM / COPY TO for bulk import/export
            - Advisory locks: SELECT pg_advisory_lock(key)
            - DDL that must run outside a transaction

            For everything else use get_db().
        """
        async with get_engine().connect() as conn:
            try:
                yield conn
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Alembic helpers — synchronous engine for migration runner
# ══════════════════════════════════════════════════════════════════════════════


def get_sync_engine():  # type: ignore[return]
    """
    Return a synchronous SQLAlchemy engine for Alembic.
    Alembic does not support asyncpg — it needs a psycopg2 connection.

    This function is called exclusively from alembic/env.py.
    It is never used by the application at runtime.
    """
    from sqlalchemy import create_engine as _create_engine

    return _create_engine(
        str(settings.database_sync_url),
        # No connection pool needed for Alembic — it runs migrations
        # sequentially in a single process.
        poolclass=None,  # type: ignore[arg-type]
        echo=True,
        connect_args={"options": "-c timezone=UTC -c application_name=alembic"},
    )
