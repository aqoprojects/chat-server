from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Module-level SHA1 constants ───────────────────────────────────────────────
# Set by load_all_scripts() at startup.
# Every caller does: from cache.scripts import TOKEN_BUCKET_SHA
# and then: await redis.evalsha(TOKEN_BUCKET_SHA, 1, key, ...)

TOKEN_BUCKET_SHA:  Optional[str] = None
IDEMPOTENCY_SHA:   Optional[str] = None

# Path to the directory containing .lua files
_SCRIPTS_DIR = Path(__file__).parent


async def load_all_scripts() -> None:
    """
    Load all Lua scripts into Redis using SCRIPT LOAD.

    SCRIPT LOAD sends the script text to Redis and returns its SHA1 hash.
    Redis caches the script permanently (until SCRIPT FLUSH is called or
    Redis restarts — scripts are not persisted across restarts).

    The returned SHAs are stored in module-level variables so every caller
    can use EVALSHA without re-reading the file or sending the full script.

    Called once from app/lifespan.py during application startup, before
    any request is served.
    """
    global TOKEN_BUCKET_SHA, IDEMPOTENCY_SHA

    from cache.client import get_redis_client

    redis = get_redis_client()

    try:
        # ── Token bucket script ───────────────────────────────────────────────
        token_bucket_path = _SCRIPTS_DIR / "token_bucket.lua"
        token_bucket_src  = token_bucket_path.read_text(encoding="utf-8")
        TOKEN_BUCKET_SHA  = await redis.script_load(token_bucket_src)

        log.info(
            "lua_script_loaded",
            script="token_bucket",
            sha=TOKEN_BUCKET_SHA[:8] + "...",   # log prefix only — full SHA is 40 chars
        )

        # ── Idempotency script ────────────────────────────────────────────────
        idempotency_path = _SCRIPTS_DIR / "idempotency.lua"
        idempotency_src  = idempotency_path.read_text(encoding="utf-8")
        IDEMPOTENCY_SHA  = await redis.script_load(idempotency_src)

        log.info(
            "lua_script_loaded",
            script="idempotency",
            sha=IDEMPOTENCY_SHA[:8] + "...",
        )

    except Exception as exc:
        log.error("lua_script_load_failed", error=str(exc))
        raise

    finally:
        await redis.aclose()


async def reload_scripts() -> None:
    """
    Reload all Lua scripts after a Redis restart.

    Redis does not persist scripts across restarts. If Redis restarts
    and EVALSHA is called with a previously loaded SHA, Redis returns
    a NOSCRIPT error. This function is called by the Redis auto-reconnect
    handler to restore scripts after reconnection.
    """
    log.warning("reloading_lua_scripts_after_redis_restart")
    await load_all_scripts()