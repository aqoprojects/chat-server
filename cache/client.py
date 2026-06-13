from __future__ import annotations

# Full implementation in Stage 3 Topic 4.

_pool = None


async def init_redis_pool() -> None:
    raise NotImplementedError("cache/client.py not yet implemented")


async def close_redis_pool() -> None:
    pass


async def get_redis_client():  # type: ignore[return]
    raise NotImplementedError("cache/client.py not yet implemented")