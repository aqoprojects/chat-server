from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


async def check_db() -> bool:
    """
    Execute a trivial query against the database.
    Returns True if the database is reachable, False otherwise.
    """
    try:
        from db.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("db_health_check_failed", error=str(exc))
        return False


async def check_redis() -> bool:
    """
    Send a PING to Redis.
    Returns True if Redis is reachable, False otherwise.
    """
    try:
        from cache.client import get_redis_client

        redis = await get_redis_client()
        await redis.ping()
        return True
    except Exception as exc:
        log.warning("redis_health_check_failed", error=str(exc))
        return False