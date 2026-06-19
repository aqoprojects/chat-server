from __future__ import annotations

from typing import NamedTuple

import structlog
from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from cache.keys import rate_limit_key, rate_limit_chat_key
from core.config import settings
from core.exceptions import RateLimitExceededError

log = structlog.get_logger(__name__)


class RateLimitResult(NamedTuple):
    allowed:     bool
    remaining:   int
    retry_after: int   # seconds until request can be retried (0 if allowed)


async def check_rate_limit(
    redis: Redis,
    *,
    action: str,
    identifier: str,
    capacity: float,
    rate: float,
    requested: float = 1.0,
    ttl_seconds: int | None = None,
) -> RateLimitResult:
    """
    Execute the token bucket Lua script for a specific action + identifier.

    This is the single entry point for all rate limit checks.
    Called from FastAPI dependencies in app/dependencies/rate_limit.py.

    Args:
        redis       : Redis client from get_redis() dependency.
        action      : Short label for the endpoint being rate-limited.
        e.g. "login", "post_create", "msg_global"
        identifier  : The value being rate-limited.
        Unauthenticated: client IP address (str).
        Authenticated: user UUID (str).
        capacity    : Maximum tokens in the bucket.
        rate        : Tokens added per second (refill rate).
        requested   : Tokens this request consumes (default 1.0).
        ttl_seconds : Key TTL in seconds. Defaults to 2 × (capacity / rate),
        which ensures the key lives long enough to prevent
        bucket reset between normal requests.

        Returns:
            RateLimitResult(allowed, remaining, retry_after)

            Raises:
                RateLimitExceededError: if allowed is False.
                The exception carries retry_after so the
                global exception handler can set Retry-After.
                """
    from cache.scripts import TOKEN_BUCKET_SHA, reload_scripts

    if TOKEN_BUCKET_SHA is None:
        # Scripts not loaded yet — should not happen after startup.
        # Reload defensively and continue.
        log.warning("token_bucket_sha_not_loaded_reloading")
        await reload_scripts()
        from cache.scripts import TOKEN_BUCKET_SHA as sha_after_reload
        if sha_after_reload is None:
            raise RuntimeError("Token bucket Lua script could not be loaded")

    bucket_key = rate_limit_key(action, identifier)

    if ttl_seconds is None:
        # Default TTL: 2× the time to fill an empty bucket.
        # Ensures the key persists through a quiet period without expiring
        # prematurely and resetting a partially-consumed bucket.
        ttl_seconds = max(60, int(2 * capacity / rate))

    try:
        result = await _evalsha_with_fallback(
            redis=redis,
            sha=TOKEN_BUCKET_SHA,
            keys=[bucket_key],
            args=[
                str(capacity),
                str(rate),
                str(requested),
                str(ttl_seconds),
            ],
        )
    except Exception as exc:
        # On any unexpected Redis error, fail open — allow the request.
        # Rate limiting failure should never cause legitimate requests
        # to fail in production. Log loudly so the issue is investigated.
        log.error(
            "rate_limit_check_failed_failing_open",
            action=action,
            identifier=identifier,
            error=str(exc),
        )
        return RateLimitResult(allowed=True, remaining=0, retry_after=0)

    allowed      = bool(result[0])
    remaining    = int(result[1])
    retry_after  = int(result[2])

    if not allowed:
        log.warning(
            "rate_limit_exceeded",
            action=action,
            identifier=identifier,
            retry_after=retry_after,
        )
        raise RateLimitExceededError(
    message=(
        f"Rate limit exceeded for '{action}'. "
        f"Try again in {retry_after} second(s)."
    ),
    retry_after=retry_after,
    )

    log.debug(
        "rate_limit_allowed",
        action=action,
        identifier=identifier,
        remaining=remaining,
    )

    return RateLimitResult(
        allowed=True,
        remaining=remaining,
        retry_after=0,
    )


async def check_chat_rate_limit(
    redis: Redis,
    *,
    user_id: str,
    chat_id: str,
    capacity: float,
    rate: float,
    requested: float = 1.0,
) -> RateLimitResult:
    """
    Per-chat token bucket rate limit check.

    Uses rate_limit_chat_key() which produces:
        rl:msg_chat:<user_id>:<chat_id>

        Called by the message send endpoint for the per-chat limit (separate
from the global per-user message limit which uses check_rate_limit()).
"""
    from cache.scripts import TOKEN_BUCKET_SHA, reload_scripts

    if TOKEN_BUCKET_SHA is None:
        await reload_scripts()

    bucket_key  = rate_limit_chat_key("msg_chat", user_id, chat_id)
    ttl_seconds = max(60, int(2 * capacity / rate))

    try:
        result = await _evalsha_with_fallback(
            redis=redis,
            sha=TOKEN_BUCKET_SHA,
            keys=[bucket_key],
            args=[
                str(capacity),
                str(rate),
                str(1.0),          # always 1 token per message
                str(ttl_seconds),
            ],
        )
    except Exception as exc:
        log.error(
            "chat_rate_limit_check_failed_failing_open",
            user_id=user_id,
            chat_id=chat_id,
            error=str(exc),
        )
        return RateLimitResult(allowed=True, remaining=0, retry_after=0)

    allowed     = bool(result[0])
    remaining   = int(result[1])
    retry_after = int(result[2])

    if not allowed:
        raise RateLimitExceededError(
            message=(
                f"Message rate limit exceeded in this chat. "
                f"Try again in {retry_after} second(s)."
            ),
            retry_after=retry_after,
    )

    return RateLimitResult(allowed=True, remaining=remaining, retry_after=0)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helper — EVALSHA with automatic NOSCRIPT recovery
# ══════════════════════════════════════════════════════════════════════════════

async def _evalsha_with_fallback(
    redis: Redis,
    sha: str,
    keys: list[str],
    args: list[str],
) -> list:
    """
    Call EVALSHA and handle NOSCRIPT errors transparently.

    Redis returns NOSCRIPT when the script SHA is not in its cache —
    this happens after a Redis restart (scripts are not persisted).
    On NOSCRIPT: reload all scripts and retry once with the new SHA.

    If the retry also fails, the exception propagates to check_rate_limit()
    which fails open (allows the request) and logs the error.
    """
    try:
        return await redis.evalsha(sha, len(keys), *keys, *args)   # type: ignore[no-untyped-call]
    except NoScriptError:
        log.warning(
            "evalsha_noscript_reloading",
            sha_prefix=sha[:8],
        )
        # Reload scripts — this updates the module-level SHA constants
        from cache.scripts import reload_scripts
        await reload_scripts()

        # Import the fresh SHA after reload
        from cache.scripts import TOKEN_BUCKET_SHA as fresh_sha
        if fresh_sha is None:
            raise RuntimeError("Script reload failed — SHA still None")

        # Retry with the fresh SHA
        return await redis.evalsha(fresh_sha, len(keys), *keys, *args)   # type: ignore[no-untyped-call]