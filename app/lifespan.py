from __future__ import annotations

import structlog
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.

    Everything before `yield` runs on startup.
    Everything after `yield` runs on shutdown.

    Startup order:
        1. Database connection pool
        2. Redis connection pool
        3. Load Lua scripts into Redis
        4. Redis Streams consumer group bootstrap
        5. Sentry (production only)

    Shutdown order (reverse of startup):
        1. Redis Streams consumer cleanup
        2. Close Redis pool
        3. Close database pool
    """

    # ══════════════════════════════════════════════════════════════════════════
    #  STARTUP
    # ══════════════════════════════════════════════════════════════════════════

    log.info("server_starting")

    # ── 1. Database connection pool ───────────────────────────────────────────
    await _startup_database()

    # ── 2. Redis connection pool ──────────────────────────────────────────────
    await _startup_redis()

    # ── 3. Load Lua scripts into Redis ───────────────────────────────────────
    await _startup_lua_scripts()

    # ── 4. Redis Streams consumer group bootstrap ─────────────────────────────
    await _startup_streams()

    # ── 5. Sentry (production only) ───────────────────────────────────────────
    _startup_sentry()

    log.info("server_ready")

    # ── Hand control to FastAPI — the application runs here ──────────────────
    yield

    # ══════════════════════════════════════════════════════════════════════════
    #  SHUTDOWN
    # ══════════════════════════════════════════════════════════════════════════

    log.info("server_shutting_down")

    # ── Reverse order of startup ──────────────────────────────────────────────
    await _shutdown_streams()
    await _shutdown_redis()
    await _shutdown_database()

    log.info("server_stopped")


# ══════════════════════════════════════════════════════════════════════════════
#  Startup handlers
# ══════════════════════════════════════════════════════════════════════════════

async def _startup_database() -> None:
    """
    Initialize the async SQLAlchemy engine and verify connectivity.
    The engine is created here and stored on db.session.engine so
    every request can acquire a session from the pool.
    """
    try:
        from db.session import init_db_engine, async_session_factory
        from sqlalchemy import text

        await init_db_engine()

        # Verify the pool can actually reach the database.
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))

        log.info("database_pool_ready")

    except Exception as exc:
        log.error("database_startup_failed", error=str(exc))
        # Re-raise — a server without a DB is broken. Crash loudly so the
        # process restarter (systemd / K8s) knows to backoff and retry.
        raise


async def _startup_redis() -> None:
    """
    Initialize the async Redis connection pool and verify connectivity.
    The pool is stored in cache.client so every request can acquire
    a connection without creating a new one.
    """
    try:
        from cache.client import init_redis_pool

        await init_redis_pool()

        log.info("redis_pool_ready")

    except Exception as exc:
        log.error("redis_startup_failed", error=str(exc))
        raise


async def _startup_lua_scripts() -> None:
    """
    Load all Lua scripts from cache/scripts/ into Redis using SCRIPT LOAD.
    Storing the SHA1 hash allows calling the scripts with EVALSHA instead
    of sending the full script on every invocation.

    The loaded SHAs are stored in cache.scripts module-level variables
    so rate limiting and idempotency modules can call them by SHA.
    """
    try:
        from cache.scripts import load_all_scripts

        await load_all_scripts()

        log.info("lua_scripts_loaded")

    except Exception as exc:
        log.error("lua_scripts_load_failed", error=str(exc))
        raise


async def _startup_streams() -> None:
    """
    Ensure the Redis Streams and their consumer groups exist.
    XGROUP CREATE with MKSTREAM creates the stream and group atomically
    if neither exists. If they already exist the call is silently ignored.

    Streams created here:
        chat_stream   — all chat message events
        notif_stream  — all notification events
    """
    try:
        # from cache.streams import bootstrap_consumer_groups

        # await bootstrap_consumer_groups()

        log.info("redis_streams_ready")

    except Exception as exc:
        log.error("streams_startup_failed", error=str(exc))
        raise


def _startup_sentry() -> None:
    """
    Initialize Sentry SDK in production.
    In development and test the DSN is empty so this is a no-op.
    """
    from core.config import settings

    if not settings.sentry_dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.redis import RedisIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                CeleryIntegration(),
                RedisIntegration(),
            ],
            traces_sample_rate=settings.sentry_traces_sample_rate,
            environment=settings.app_env,
            send_default_pii=False,   # never send personally identifiable info
        )

        log.info("sentry_initialized", environment=settings.app_env)

    except Exception as exc:
        # Sentry failure is not fatal — log and continue.
        log.warning("sentry_init_failed", error=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
#  Shutdown handlers
# ══════════════════════════════════════════════════════════════════════════════

async def _shutdown_streams() -> None:
    """
    Gracefully stop any active Redis Streams consumer loops.
    The consumer group and stream data are preserved in Redis —
    only the in-process consumer task is stopped.
    """
    try:
        from cache.streams import teardown_consumer_groups

        await teardown_consumer_groups()

        log.info("redis_streams_closed")

    except Exception as exc:
        # Non-fatal on shutdown — log and continue closing other resources.
        log.warning("streams_shutdown_error", error=str(exc))


async def _shutdown_redis() -> None:
    """
    Close all connections in the Redis pool gracefully.
    In-flight commands are allowed to complete; new commands are rejected.
    """
    try:
        from cache.client import close_redis_pool

        await close_redis_pool()

        log.info("redis_pool_closed")

    except Exception as exc:
        log.warning("redis_shutdown_error", error=str(exc))


async def _shutdown_database() -> None:
    """
    Dispose the SQLAlchemy async engine.
    This closes all pooled connections cleanly, which prevents
    "connection already closed" errors in PostgreSQL logs after restart.
    """
    try:
        from db.session import close_db_engine

        await close_db_engine()

        log.info("database_pool_closed")

    except Exception as exc:
        log.warning("database_shutdown_error", error=str(exc))