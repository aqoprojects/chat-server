from __future__ import annotations

# Full implementation in Stage 3 Topic 3.
# Stubs allow lifespan.py to import this file without crashing.

engine = None
async_session_factory = None  # type: ignore[assignment]


async def init_db_engine() -> None:
    raise NotImplementedError("db/session.py not yet implemented")


async def close_db_engine() -> None:
    pass