from __future__ import annotations

import time
from typing import TypedDict

import structlog

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Result types
# ══════════════════════════════════════════════════════════════════════════════

class CheckResult(TypedDict):
    ok: bool
    latency_ms: float
    detail: str


    # ══════════════════════════════════════════════════════════════════════════════
    #  Individual dependency checks
    # ══════════════════════════════════════════════════════════════════════════════

async def check_db() -> CheckResult:
    """
    Verify the PostgreSQL connection pool is alive and responsive.

    Executes SELECT 1 using a fresh session from the pool.
    Records wall-clock latency in milliseconds.

    Returns a CheckResult with:
        ok          — True if the query succeeded, False otherwise.
        latency_ms  — Round-trip time for the query in milliseconds.
        detail      — Human-readable status or error message.
        """
    start = time.monotonic()

    try:
        from db.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))

            latency_ms = (time.monotonic() - start) * 1000

            log.debug("db_health_check_ok", latency_ms=round(latency_ms, 2))

            return CheckResult(
            ok=True,
            latency_ms=round(latency_ms, 2),
            detail="ok",
            )

    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000

        log.warning(
            "db_health_check_failed",
            error=str(exc),
            latency_ms=round(latency_ms, 2),
        )

        return CheckResult(
            ok=False,
            latency_ms=round(latency_ms, 2),
            detail=f"unreachable: {type(exc).__name__}",
        )


async def check_redis() -> CheckResult:
    """
    Verify the Redis app cache pool (DB 0) is alive and responsive.

    Sends PING and expects PONG.
    Records wall-clock latency in milliseconds.

    Returns a CheckResult with the same shape as check_db().
    """
    start = time.monotonic()

    try:
        from cache.client import get_redis_client

        redis = get_redis_client()
        response = await redis.ping()
        await redis.aclose()

        latency_ms = (time.monotonic() - start) * 1000

        if not response:
            raise RuntimeError("PING returned falsy response")

        log.debug("redis_health_check_ok", latency_ms=round(latency_ms, 2))

        return CheckResult(
        ok=True,
        latency_ms=round(latency_ms, 2),
        detail="ok",
        )

    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000

        log.warning(
            "redis_health_check_failed",
            error=str(exc),
            latency_ms=round(latency_ms, 2),
        )

        return CheckResult(
    ok=False,
    latency_ms=round(latency_ms, 2),
    detail=f"unreachable: {type(exc).__name__}",
)