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


# ══════════════════════════════════════════════════════════════════════════════
#  Per-user rate limit wrapper
#  Higher-level API used by services and WebSocket handlers directly,
#  without going through FastAPI Depends().
# ══════════════════════════════════════════════════════════════════════════════

# Maps action name → (capacity_attr, rate_attr) on settings
# Every action that has a rate limit must appear here.
_ACTION_SETTINGS_MAP: dict[str, tuple[str, str]] = {
    "register":      ("rate_limit_register_capacity",
    "rate_limit_register_refill_rate"),
    "verify":        ("rate_limit_verify_capacity",
    "rate_limit_verify_refill_rate"),
    "resend_verify": ("rate_limit_resend_verify_capacity",
    "rate_limit_resend_verify_refill_rate"),
    "login":         ("rate_limit_login_capacity",
    "rate_limit_login_refill_rate"),
    "refresh":       ("rate_limit_refresh_capacity",
    "rate_limit_refresh_refill_rate"),
    "profile_edit":  ("rate_limit_profile_edit_capacity",
    "rate_limit_profile_edit_refill_rate"),
    "follow":        ("rate_limit_follow_capacity",
    "rate_limit_follow_refill_rate"),
    "post_create":   ("rate_limit_post_create_capacity",
    "rate_limit_post_create_refill_rate"),
    "reply_create":  ("rate_limit_reply_create_capacity",
    "rate_limit_reply_create_refill_rate"),
    "like":          ("rate_limit_like_capacity",
    "rate_limit_like_refill_rate"),
    "search":        ("rate_limit_search_capacity",
    "rate_limit_search_refill_rate"),
    "msg_global":    ("rate_limit_message_global_capacity",
    "rate_limit_message_global_refill_rate"),
    "msg_chat":      ("rate_limit_message_per_chat_capacity",
    "rate_limit_message_per_chat_refill_rate"),
    "interest":      ("rate_limit_interest_capacity",
    "rate_limit_interest_refill_rate"),
}


async def enforce_rate_limit(
    redis: Redis,
    *,
    action: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    requested: float = 1.0,
) -> RateLimitResult:
    """
    High-level rate limit enforcer that resolves settings automatically.

    Selects the identifier based on authentication state:
        - user_id provided   → authenticated, rate-limit by user UUID
        - ip_address provided → unauthenticated, rate-limit by IP
        - both provided      → user_id takes precedence

        Looks up capacity and rate from settings via _ACTION_SETTINGS_MAP.
        Raises RateLimitExceededError if the limit is exceeded (same as
        check_rate_limit — propagates to the global exception handler).

        Args:
            redis      : Redis client (from get_redis dependency or directly).
            action     : Action label — must be a key in _ACTION_SETTINGS_MAP.
            user_id    : Authenticated user UUID string (preferred identifier).
            ip_address : Client IP string (fallback for pre-auth endpoints).
            requested  : Token cost of this request (default 1.0).

            Returns:
                RateLimitResult(allowed=True, remaining, retry_after=0)
                (Denied requests raise RateLimitExceededError, never return False)

                Example (in a service function):
                    await enforce_rate_limit(redis, action="post_create", user_id=str(user.id))

                    Example (in a WebSocket handler, no Depends() available):
                        await enforce_rate_limit(redis, action="msg_global", user_id=str(user_id))
                        """
    if action not in _ACTION_SETTINGS_MAP:
        raise ValueError(
            f"Unknown rate limit action: '{action}'. "
            f"Add it to _ACTION_SETTINGS_MAP in cache/rate_limit.py."
        )

    capacity_attr, rate_attr = _ACTION_SETTINGS_MAP[action]
    capacity = float(getattr(settings, capacity_attr))
    rate     = float(getattr(settings, rate_attr))

    # Resolve identifier — user_id beats IP
    identifier = user_id if user_id else ip_address
    if not identifier:
        raise ValueError(
            "enforce_rate_limit requires either user_id or ip_address."
        )

    return await check_rate_limit(
        redis,
        action=action,
        identifier=identifier,
        capacity=capacity,
        rate=rate,
        requested=requested,
    )


async def enforce_chat_rate_limit(
    redis: Redis,
    *,
    user_id: str,
    chat_id: str,
    requested: float = 1.0,
) -> RateLimitResult:
    """
    Per-chat message rate limit enforcer.

    Convenience wrapper around check_chat_rate_limit() that pulls
    capacity and rate from settings automatically.

    Used by the WebSocket message handler and the REST message send endpoint.

    Example:
        await enforce_chat_rate_limit(redis, user_id=str(uid), chat_id=str(cid))
        """
    return await check_chat_rate_limit(
        redis,
        user_id=user_id,
        chat_id=chat_id,
        capacity=float(settings.rate_limit_message_per_chat_capacity),
        rate=float(settings.rate_limit_message_per_chat_refill_rate),
        requested=requested,
    )


from fastapi.responses import Response as FastAPIResponse

def apply_rate_limit_headers(
    response: FastAPIResponse,
    result: RateLimitResult,
    capacity: int,
) -> None:
    """
    Attach standard rate limit headers to an HTTP response.

    Headers added:
        X-RateLimit-Limit     : Maximum requests allowed in the window
        X-RateLimit-Remaining : Requests remaining in the current window
        X-RateLimit-Retry-After: Seconds to wait before retrying (0 if allowed)

        These headers follow the IETF draft-ietf-httpapi-ratelimit-headers spec.
        Frontend clients should read X-RateLimit-Remaining and back off
        proactively when it approaches 0, rather than waiting for a 429.

        Called from route handlers after a successful rate limit check:

            result = await enforce_rate_limit(redis, action="post_create", user_id=uid)
            apply_rate_limit_headers(response, result, capacity=settings.rate_limit_post_create_capacity)
            """
    response.headers["X-RateLimit-Limit"]       = str(capacity)
    response.headers["X-RateLimit-Remaining"]   = str(result.remaining)
    response.headers["X-RateLimit-Retry-After"] = str(result.retry_after)



import re

# Compiled once at module load — not per request
_SPAM_PATTERNS: list[re.Pattern[str]] = [
    # Repeated single character runs (aaaaaaa, 1111111)
    re.compile(r'(.)\1{9,}', re.UNICODE),
    # Repeated word spam (buy buy buy buy buy)
    re.compile(r'\b(\w+)(\s+\1){4,}\b', re.IGNORECASE | re.UNICODE),
    # ALL CAPS long strings (shouting)
    re.compile(r'[A-Z\s]{30,}'),
    # Excessive punctuation
    re.compile(r'[!?]{5,}'),
    # URL spam — more than 3 URLs in one message
    re.compile(r'(https?://\S+\s*){4,}', re.IGNORECASE),
]


def is_spam_content(content: str) -> bool:
    """
    Quick pattern-based spam detection for message content.

    Runs synchronously — no I/O. Called before the token bucket check
    so spam is rejected without consuming a rate limit token.

    Detected patterns:
        - Character repetition runs (10+ same char)
        - Word repetition spam (5+ same word in sequence)
        - ALL CAPS messages (30+ characters)
        - Excessive punctuation (5+ ! or ? in a row)
        - URL flooding (4+ URLs in one message)

        Returns True if content looks like spam, False if clean.

        Content moderation hooks (Celery tasks) run a deeper analysis
        asynchronously after the message is stored — this is only a
        fast first-pass filter.
        """
    if not content or not content.strip():
        return False

    for pattern in _SPAM_PATTERNS:
        if pattern.search(content):
            return True

        return False


async def enforce_message_rate_limits(
    redis: Redis,
    *,
    user_id: str,
    chat_id: str,
    content: str,
) -> None:
    """
    Combined message rate limit enforcement for chat message sends.

    Runs three checks in order:
        1. Spam content detection (synchronous, no Redis I/O)
        2. Global per-user message rate limit
        3. Per-chat per-user message rate limit

        Raises RateLimitExceededError on any violation.
        Called from the message service before writing to DB or Redis Stream.

        Args:
            redis    : Redis client.
            user_id  : Sender's user UUID string.
            chat_id  : Target chat UUID string.
            content  : Message content string (for spam detection).
            """
    from core.exceptions import BadRequestError

    # 1. Spam detection (fast, no I/O)
    if content and is_spam_content(content):
        raise BadRequestError(
            "Your message was flagged as spam. "
            "Please avoid repetitive content."
        )

    # 2. Global per-user rate limit
    await enforce_rate_limit(
        redis,
        action="msg_global",
        user_id=user_id,
    )

    # 3. Per-chat rate limit
    await enforce_chat_rate_limit(
        redis,
        user_id=user_id,
        chat_id=chat_id,
    )
