from __future__ import annotations

import json
from typing import Any

import structlog
from redis.asyncio import Redis

from cache.keys import idempotency_key
from cache.scripts import IDEMPOTENCY_SHA, reload_scripts
from core.config import settings

log = structlog.get_logger(__name__)

# ── TTL constants ─────────────────────────────────────────────────────────────
# How long a request is allowed to be "in processing" state.
# If the server crashes after reserving but before storing, this ensures
# the client can retry after 30 seconds without being permanently blocked.
_PROCESSING_TTL: int = 30

# How long the cached response is held for replay.
# Matches settings.idempotency_ttl (86400 seconds = 24 hours).
_STORE_TTL: int = settings.idempotency_ttl


class IdempotencyConflict(Exception):
    """
    Raised when a duplicate request is detected and the original is
    still processing. The caller should return 409 Conflict and advise
    the client to retry after a short delay.
    """


class IdempotencyReplay(Exception):
    """
    Raised when a cached response exists for this idempotency key.
    The caller should return the cached response directly without
    re-processing the request.

    Attributes:
        status_code : Original HTTP status code of the cached response.
        body        : Original response body dict.
        """
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body        = body
        super().__init__(f"Idempotent replay: status={status_code}")


async def reserve_idempotency_key(
    redis: Redis,
    key_value: str,
) -> None:
    """
    Phase 1 — Reserve an idempotency key before processing a request.

    Atomically checks whether the key exists and sets it to "processing".

    Raises:
        IdempotencyReplay    : A cached response exists — replay it.
        IdempotencyConflict  : The key is currently being processed by
        another request — advise client to retry.

        If neither exception is raised, the key is now reserved and the
        caller should process the request, then call store_idempotency_key().

        Args:
            redis     : Redis client.
            key_value : The UUID from the client's X-Idempotency-Key header.
            """
    redis_key = idempotency_key(key_value)

    result = await _evalsha_idempotency(
        redis=redis,
        phase="reserve",
        key=redis_key,
        processing_ttl=_PROCESSING_TTL,
    )

    if result == "new":
        # Key reserved successfully — proceed with request processing.
        log.debug("idempotency_key_reserved", key_prefix=key_value[:8])
        return

    elif result == "processing":
        # Another request is currently processing this key.
        log.warning("idempotency_key_processing_conflict",
        key_prefix=key_value[:8])
        raise IdempotencyConflict(
        f"Request with idempotency key '{key_value[:8]}...' is already "
        f"being processed. Retry after a few seconds."
        )

    else:
        # Result is a JSON string — cached response from a previous request.
        try:
            cached = json.loads(result)
            log.info("idempotency_replay",
                key_prefix=key_value[:8],
                status_code=cached.get("status_code"))
            raise IdempotencyReplay(
                status_code=cached.get("status_code", 200),
                body=cached.get("body", {}),
            )
        except (json.JSONDecodeError, TypeError) as exc:
            # Corrupted cache entry — treat as new request
            log.error("idempotency_cache_corrupt",
            key_prefix=key_value[:8], error=str(exc))
            return


async def store_idempotency_key(
    redis: Redis,
    key_value: str,
    *,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """
    Phase 2 — Store the response after successful request processing.

    Must be called after every successful state-mutating operation
    that was preceded by reserve_idempotency_key().

    If the server crashes between reserve and store, the processing_ttl
    (30 seconds) ensures the key expires and the client can retry.

    Args:
        redis       : Redis client.
        key_value   : The UUID from the client's X-Idempotency-Key header.
        status_code : HTTP status code of the response to cache.
        body        : Response body dict to cache.
        """
    redis_key = idempotency_key(key_value)

    response_json = json.dumps({
        "status_code": status_code,
        "body": body,
    })

    result = await _evalsha_idempotency(
        redis=redis,
        phase="store",
        key=redis_key,
        response_json=response_json,
        store_ttl=_STORE_TTL,
    )

    if result == "ok":
        log.debug("idempotency_key_stored",
        key_prefix=key_value[:8],
        status_code=status_code,
        ttl=_STORE_TTL)
    elif result == "conflict":
        # Key already had a stored response — should not happen in normal flow.
        log.warning("idempotency_store_conflict", key_prefix=key_value[:8])
    else:
        log.error("idempotency_store_unexpected_result",
        result=result, key_prefix=key_value[:8])


async def release_idempotency_key(
    redis: Redis,
    key_value: str,
) -> None:
    """
    Release a reserved idempotency key after a failed request.

    If the request fails (validation error, DB error, etc.) after
    reserve_idempotency_key() succeeded, the key must be deleted so
    the client can retry. Without this, the client would receive
    "processing" responses for 30 seconds.

    Called in the exception handler of any endpoint that uses idempotency.

    Args:
        redis     : Redis client.
        key_value : The UUID from the client's X-Idempotency-Key header.
        """
    redis_key = idempotency_key(key_value)
    await redis.delete(redis_key)
    log.debug("idempotency_key_released", key_prefix=key_value[:8])


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI middleware helper — extract and validate idempotency key
# ══════════════════════════════════════════════════════════════════════════════

IDEMPOTENCY_HEADER = "X-Idempotency-Key"


def extract_idempotency_key(headers: dict[str, str]) -> str | None:
    """
    Extract and validate the X-Idempotency-Key header value.

    Validation:
        - Must be present (returns None if absent — endpoint decides if required)
        - Must be a valid UUID v4 format
        - Must be exactly 36 characters

        Returns the key string if valid, None if absent, raises ValueError if malformed.
        """
    import uuid as _uuid

    raw = headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not raw:
        return None                 

    try:
        parsed = _uuid.UUID(raw, version=4)
        return str(parsed)   # normalised lowercase hyphenated form
    except ValueError:
        raise ValueError(
            f"Invalid {IDEMPOTENCY_HEADER} header: must be a UUID v4. "
            f"Received: '{raw[:36]}'"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Internal EVALSHA helper
# ══════════════════════════════════════════════════════════════════════════════

async def _evalsha_idempotency(
    redis: Redis,
    phase: str,
    key: str,
    response_json: str = "",
    processing_ttl: int = _PROCESSING_TTL,
    store_ttl: int = _STORE_TTL,
) -> str:
    """
    Call the idempotency Lua script via EVALSHA.
    Handles NOSCRIPT recovery transparently (same pattern as rate_limit.py).
    """
    from redis.exceptions import NoScriptError

    sha = IDEMPOTENCY_SHA

    if sha is None:
        await reload_scripts()
        from cache.scripts import IDEMPOTENCY_SHA as fresh_sha
        sha = fresh_sha
        if sha is None:
            raise RuntimeError("Idempotency Lua script could not be loaded")

    args = [phase, response_json, str(processing_ttl), str(store_ttl)]

    try:
        result = await redis.evalsha(sha, 1, key, *args)   # type: ignore[no-untyped-call]
        return result if isinstance(result, str) else result.decode("utf-8")

    except NoScriptError:
        log.warning("idempotency_evalsha_noscript_reloading")
        await reload_scripts()
        from cache.scripts import IDEMPOTENCY_SHA as fresh_sha
        result = await redis.evalsha(fresh_sha, 1, key, *args)   # type: ignore[no-untyped-call]
        return result if isinstance(result, str) else result.decode("utf-8")