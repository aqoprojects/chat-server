from __future__ import annotations

from typing import Optional, AsyncGenerator

import structlog
import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.config import settings

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level pool singletons
#  Both are None until init_redis_pool() is called from lifespan.py
# ══════════════════════════════════════════════════════════════════════════════

# DB 0 — application cache (sessions, rate limits, presence, unread counts,
#         idempotency keys, verification codes, username cooldowns)
_app_pool: Optional[ConnectionPool] = None

# DB 2 — Redis Streams (chat events, notification events)
_stream_pool: Optional[ConnectionPool] = None


# ══════════════════════════════════════════════════════════════════════════════
#  Pool initialisation (called once from lifespan.py on startup)
# ══════════════════════════════════════════════════════════════════════════════

async def init_redis_pool() -> None:
    """
    Create async connection pools for each Redis DB index.
    Verifies connectivity by sending PING on each pool.

    Pool sizes come from core.config.settings so they can be tuned
    per environment. Two pools are created:
        _app_pool    → DB 0  (application cache)
        _stream_pool → DB 2  (Redis Streams)

        Celery manages its own internal pool via CELERY_RESULT_BACKEND and
        CELERY_BROKER_URL — we never manage that pool here.
        """
    global _app_pool, _stream_pool

    if _app_pool is not None:
        log.warning("redis_pool_already_initialised")
        return

    # ── Build shared connection kwargs ────────────────────────────────────────
    # These are identical for both pools — only the db index differs.
    base_kwargs: dict = {
        "host": settings.redis_host,
        "port": settings.redis_port,
        "password": settings.redis_password or None,
        "max_connections": settings.redis_max_connections,
        "socket_timeout": settings.redis_socket_timeout,
        "socket_connect_timeout": settings.redis_socket_connect_timeout,
        "retry_on_timeout": settings.redis_retry_on_timeout,
        # decode_responses=True: Redis returns str instead of bytes.
        # This is the correct setting for a Python application that works
        # with string keys and values. Only set to False if you are storing
        # raw binary data (e.g. serialised protobuf), which we are not.
        "decode_responses": True,
        # health_check_interval: redis-py automatically sends a PING on
        # idle connections every N seconds. This keeps NAT mappings alive
        # and surfaces dead connections before they are handed to a caller.
        "health_check_interval": 30,
    }

    # ── App cache pool (DB 0) ─────────────────────────────────────────────────
    _app_pool = ConnectionPool(
        db=settings.redis_db_app,
        **base_kwargs,
    )

    # Verify connectivity
    app_client = Redis(connection_pool=_app_pool)
    try:
        await app_client.ping()
        log.info(
            "redis_app_pool_ready",
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db_app,
            max_connections=settings.redis_max_connections,
        )
    except (RedisConnectionError, RedisTimeoutError) as exc:
        log.error("redis_app_pool_ping_failed", error=str(exc))
        raise
    finally:
        await app_client.aclose()

    # ── Stream pool (DB 2) ────────────────────────────────────────────────────
    _stream_pool = ConnectionPool(
        db=settings.redis_db_streams,
        **base_kwargs,
    )

    stream_client = Redis(connection_pool=_stream_pool)
    try:
        await stream_client.ping()
        log.info(
            "redis_stream_pool_ready",
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db_streams,
        )
    except (RedisConnectionError, RedisTimeoutError) as exc:
        log.error("redis_stream_pool_ping_failed", error=str(exc))
        raise
    finally:
        await stream_client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
#  Pool teardown (called from lifespan.py on shutdown)
# ══════════════════════════════════════════════════════════════════════════════

async def close_redis_pool() -> None:
    """
    Disconnect all connections in both pools gracefully.
    In-flight commands are allowed to complete; new commands are rejected.
    Called from lifespan.py during shutdown.
    """
    global _app_pool, _stream_pool

    if _app_pool is not None:
        await _app_pool.aclose()
        _app_pool = None
        log.info("redis_app_pool_closed")

        if _stream_pool is not None:
            await _stream_pool.aclose()
            _stream_pool = None
            log.info("redis_stream_pool_closed")


# ══════════════════════════════════════════════════════════════════════════════
#  Public client accessors
# ══════════════════════════════════════════════════════════════════════════════

def get_redis_client() -> Redis:
    """
    Return a Redis client bound to the app cache pool (DB 0).

    This is a synchronous function that returns instantly — it does not
    open a new connection. The client borrows a connection from the pool
    only when it executes a command.

    Used by:
        - lifespan.py startup ping (via await get_redis_client().ping())
        - cache/keys.py key builders
        - cache/scripts/ Lua script callers
        - services that need atomic Redis operations directly
        - the get_redis() FastAPI dependency below
        """
    if _app_pool is None:
        raise RuntimeError(
        "Redis app pool is not initialised. "
        "Ensure init_redis_pool() is called during application startup."
        )
    return Redis(connection_pool=_app_pool)


def get_stream_client() -> Redis:
    """
    Return a Redis client bound to the stream pool (DB 2).

    Used exclusively by:
        - cache/streams.py  — XADD, XREADGROUP, XACK, XCLAIM, XAUTOCLAIM
        - workers/tasks/stream_tasks.py — XTRIM, XPENDING monitoring

        Never use this client for application cache operations — keep DB 0
        and DB 2 traffic isolated so stream I/O does not exhaust the cache pool.
        """
    if _stream_pool is None:
        raise RuntimeError(
        "Redis stream pool is not initialised. "
        "Ensure init_redis_pool() is called during application startup."
        )
    return Redis(connection_pool=_stream_pool)


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI dependencies
# ══════════════════════════════════════════════════════════════════════════════

async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency that yields a Redis client for the app cache pool.

    Usage in a route or service dependency:
from cache.client import get_redis
from redis.asyncio import Redis

@router.post("/example")
async def example(redis: Redis = Depends(get_redis)):
    await redis.set("key", "value", ex=60)

    The client is created from the pool on entry and closed on exit.
    "Closing" a pooled client does not close the underlying connection —
    it returns it to the pool. This is safe and cheap.

    Why yield instead of just returning:
        The try/finally guarantees the client is always closed back to
        the pool even if the route raises an exception.
        """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def get_stream_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency that yields a Redis client for the stream pool (DB 2).

    Used by WebSocket handlers and Celery tasks that interact with
    Redis Streams directly.
    """
    client = get_stream_client()
    try:
        yield client
    finally:
        await client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
#  Utility — create a standalone client outside the FastAPI request cycle
# ══════════════════════════════════════════════════════════════════════════════

def get_redis_for_script() -> Redis:
    """
    Return a Redis client for use in Celery tasks and scripts that run
    outside the FastAPI request cycle (no Depends() available).

    Unlike the FastAPI dependency, this does not use a context manager.
    Callers are responsible for calling await client.aclose() themselves,
    or using it as an async context manager:

        async with get_redis_for_script() as redis:
            await redis.get("key")
            """
    return get_redis_client()