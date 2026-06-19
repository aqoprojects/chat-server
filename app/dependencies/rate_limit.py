from __future__ import annotations

from fastapi import Depends, Request
from redis.asyncio import Redis

from cache.client import get_redis
from cache.rate_limit import check_rate_limit, check_chat_rate_limit
from core.config import settings


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP from the request.
    Reads X-Forwarded-For if behind a reverse proxy (nginx / K8s ingress).
    Falls back to the direct connection IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list; the first is the client.
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


    # ── Unauthenticated endpoint rate limits (IP-based) ──────────────────────────

async def rate_limit_register(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="register",
        identifier=_get_client_ip(request),
        capacity=settings.rate_limit_register_capacity,
        rate=settings.rate_limit_register_refill_rate,
    )


async def rate_limit_verify(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="verify",
        identifier=_get_client_ip(request),
        capacity=settings.rate_limit_verify_capacity,
        rate=settings.rate_limit_verify_refill_rate,
    )


async def rate_limit_resend_verify(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="resend_verify",
        identifier=_get_client_ip(request),
        capacity=settings.rate_limit_resend_verify_capacity,
        rate=settings.rate_limit_resend_verify_refill_rate,
    )


async def rate_limit_login(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="login",
        identifier=_get_client_ip(request),
        capacity=settings.rate_limit_login_capacity,
        rate=settings.rate_limit_login_refill_rate,
    )


    # ── Authenticated endpoint rate limits (user_id-based) ───────────────────────
    # These depend on get_current_user (Phase 3 Stage 12).
    # Until then they accept user_id as a string argument directly
    # and are wired properly when auth is implemented.

async def rate_limit_post_create(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="post_create",
        identifier=user_id,
        capacity=settings.rate_limit_post_create_capacity,
        rate=settings.rate_limit_post_create_refill_rate,
    )


async def rate_limit_reply_create(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="reply_create",
        identifier=user_id,
        capacity=settings.rate_limit_reply_create_capacity,
        rate=settings.rate_limit_reply_create_refill_rate,
    )


async def rate_limit_follow(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="follow",
        identifier=user_id,
        capacity=settings.rate_limit_follow_capacity,
        rate=settings.rate_limit_follow_refill_rate,
    )


async def rate_limit_like(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="like",
        identifier=user_id,
        capacity=settings.rate_limit_like_capacity,
        rate=settings.rate_limit_like_refill_rate,
    )


async def rate_limit_search(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="search",
        identifier=user_id,
        capacity=settings.rate_limit_search_capacity,
        rate=settings.rate_limit_search_refill_rate,
    )


async def rate_limit_message_global(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="msg_global",
        identifier=user_id,
        capacity=settings.rate_limit_message_global_capacity,
        rate=settings.rate_limit_message_global_refill_rate,
    )


async def rate_limit_profile_edit(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="profile_edit",
        identifier=user_id,
        capacity=settings.rate_limit_profile_edit_capacity,
        rate=settings.rate_limit_profile_edit_refill_rate,
    )


async def rate_limit_interest(
    user_id: str,
    redis: Redis = Depends(get_redis),
) -> None:
    await check_rate_limit(
        redis,
        action="interest",
        identifier=user_id,
        capacity=settings.rate_limit_interest_capacity,
        rate=settings.rate_limit_interest_refill_rate,
    )