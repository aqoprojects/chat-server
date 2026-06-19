from __future__ import annotations

import structlog
from redis.asyncio import Redis

from cache.keys import (
    user_cache_key,
    user_by_username_key,
    username_change_cooldown_key,
    chat_participants_key,
    user_chat_list_key,
    post_cache_key,
    post_like_count_key,
    user_liked_post_key,
    follower_count_key,
    following_count_key,
    notification_unread_count_key,
    unread_count_key,
    total_unread_key,
    last_read_message_key,
    presence_key,
    last_seen_key,
    search_cache_key,
)

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  User invalidation
# ══════════════════════════════════════════════════════════════════════════════

async def invalidate_user_cache(
    redis: Redis,
    *,
    user_id: str,
    old_username: str | None = None,
) -> None:
    """
    Invalidate all cached data for a user.

    Called when:
        - User edits their profile (display name, bio, avatar, location)
        - User changes their username
        - User's account is soft-deleted

        Deletes:
            user:<user_id>          — full profile cache
            uname:<old_username>    — old username → user_id mapping
            (only if username changed)

            The new username mapping is written by the service layer after the
            DB update succeeds, not here. Separation of concerns: this function
            only removes stale data.

            Args:
                redis        : Redis client.
                user_id      : UUID string of the user whose cache is being cleared.
                old_username : Previous username, if a username change occurred.
                If None, only the profile cache is cleared.
                """
    keys_to_delete: list[str] = [user_cache_key(user_id)]

    if old_username:
        keys_to_delete.append(user_by_username_key(old_username))

    deleted = await redis.delete(*keys_to_delete)

    log.debug(
        "user_cache_invalidated",
        user_id=user_id,
        keys_deleted=deleted,
        username_invalidated=old_username is not None,
    )


async def invalidate_user_search_cache(
    redis: Redis,
    *,
    user_id: str,
) -> None:
    """
    Invalidate search result caches that may include this user.

    Search results are cached with a 30-second TTL (short enough that
    full invalidation is usually unnecessary). However, for immediate
    consistency after a username change or avatar update, we use a
    scan-and-delete on the search: prefix for this user's results.

    In production with Redis Cluster, SCAN is replaced by targeting
    the correct shard via hash tags. For now (single Redis), SCAN works.

    Note: This is a best-effort invalidation. The 30-second TTL is the
    safety net — if SCAN misses any keys, they expire naturally.
    """
    cursor = 0
    pattern = f"search:*:{user_id}"
    deleted_count = 0

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
            deleted_count += len(keys)
            if cursor == 0:
                break

    log.debug(
        "search_cache_invalidated",
        user_id=user_id,
        keys_deleted=deleted_count,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Chat participant cache invalidation
# ══════════════════════════════════════════════════════════════════════════════

async def invalidate_chat_participant_cache(
    redis: Redis,
    *,
    chat_id: str,
    affected_user_ids: list[str],
) -> None:
    """
    Invalidate participant and chat list caches when membership changes.

    Called when:
        - A user joins a chat (add participant)
        - A user leaves or is removed from a chat
        - A user is banned from a chat

        Deletes:
            chat_p:<chat_id>            — participant SET for this chat
            chat_list:<user_id>         — each affected user's chat membership list

            The participant SET and all affected users' chat lists are invalidated
            together. They will be rebuilt from DB on the next access.

            Args:
                redis            : Redis client.
                chat_id          : UUID string of the chat.
                affected_user_ids: UUIDs of users whose chat_list cache is stale.
                Typically the user being added/removed, plus
                existing members if the participant set changed.
                """
    keys_to_delete = [chat_participants_key(chat_id)]
    keys_to_delete.extend(
        user_chat_list_key(uid) for uid in affected_user_ids
    )

    deleted = await redis.delete(*keys_to_delete)

    log.debug(
        "chat_participant_cache_invalidated",
        chat_id=chat_id,
        affected_users=len(affected_user_ids),
        keys_deleted=deleted,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Post cache invalidation
# ══════════════════════════════════════════════════════════════════════════════

async def invalidate_post_cache(
    redis: Redis,
    *,
    post_id: str,
) -> None:
    """
    Invalidate a post's cached data.

    Called when:
        - A post is edited (content changes)
        - A post is soft-deleted

        Deletes:
            post:<post_id>    — cached post response JSON

            Like counters (likes:<post_id>) are NOT deleted here — they are
            integer counters synced to DB by Celery beat, not cached JSON.
            They self-correct on the next sync.

            Args:
                redis   : Redis client.
                post_id : UUID string of the post.
                """
    deleted = await redis.delete(post_cache_key(post_id))

    log.debug("post_cache_invalidated", post_id=post_id, deleted=deleted)


# ══════════════════════════════════════════════════════════════════════════════
#  Unread count invalidation
# ══════════════════════════════════════════════════════════════════════════════

async def reset_unread_count(
    redis: Redis,
    *,
    user_id: str,
    chat_id: str,
    previous_unread: int | None = None,
) -> None:
    """
    Reset the unread message counter for a user in a specific chat to zero.

    Called when:
        - User calls mark-as-read on a chat
        - User sends a message (they have implicitly read up to that point)

        Operations:
            SET unread:<user_id>:<chat_id>  0
            DECRBY total_unread:<user_id>   <previous_unread>

            The previous_unread argument is used to decrement the total_unread
            counter by the exact amount being cleared, rather than fetching and
            re-summing all per-chat counts.

            If previous_unread is None, the current per-chat count is fetched
            first (one extra Redis round-trip).

            Args:
                redis           : Redis client.
                user_id         : UUID string of the user.
                chat_id         : UUID string of the chat.
                previous_unread : Known unread count before reset (optional optimisation).
                """
    per_chat_key = unread_count_key(user_id, chat_id)
    total_key = total_unread_key(user_id)

    if previous_unread is None:
        raw = await redis.get(per_chat_key)
        previous_unread = int(raw) if raw else 0

    pipe = redis.pipeline(transaction=True)
    pipe.set(per_chat_key, 0)
    if previous_unread > 0:
        pipe.decrby(total_key, previous_unread)
    await pipe.execute()

    log.debug(
        "unread_count_reset",
        user_id=user_id,
        chat_id=chat_id,
        cleared=previous_unread,
    )


async def increment_unread_count(
    redis: Redis,
    *,
    chat_id: str,
    sender_id: str,
    participant_ids: list[str],
) -> None:
    """
    Increment unread counters for all chat participants except the sender.

    Called after a message is successfully stored.

    Operations per recipient:
        INCR unread:<recipient_id>:<chat_id>
        INCR total_unread:<recipient_id>

        Uses a pipeline to send all INCR commands in one round-trip.

        Args:
            redis           : Redis client.
            chat_id         : UUID string of the chat.
            sender_id       : UUID of the message sender (excluded from increment).
            participant_ids : UUIDs of all active chat participants.
            """
    pipe = redis.pipeline(transaction=False)

    recipients = [uid for uid in participant_ids if uid != sender_id]

    for recipient_id in recipients:
        pipe.incr(unread_count_key(recipient_id, chat_id))
        pipe.incr(total_unread_key(recipient_id))

    await pipe.execute()

    log.debug(
        "unread_counts_incremented",
        chat_id=chat_id,
        recipients=len(recipients),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Notification count invalidation
# ══════════════════════════════════════════════════════════════════════════════

async def increment_notification_count(
    redis: Redis,
    *,
    user_id: str,
) -> int:
    """
    Increment the unread notification counter for a user.
    Returns the new count after increment.
    Called when a new notification is created.
    """
    key = notification_unread_count_key(user_id)
    new_val = await redis.incr(key)
    return int(new_val)


async def decrement_notification_count(
    redis: Redis,
    *,
    user_id: str,
    by: int = 1,
) -> None:
    """
    Decrement the unread notification counter for a user.
    Called when a notification is marked as read.
    Floors at 0 — never goes negative.
    """
    key         = notification_unread_count_key(user_id)
    current_raw = await redis.get(key)
    current     = int(current_raw) if current_raw else 0

    if current > 0:
        new_val = max(0, current - by)
        await redis.set(key, new_val)


async def reset_notification_count(
    redis: Redis,
    *,
    user_id: str,
) -> None:
    """
    Reset the unread notification counter to zero.
    Called when mark-all-notifications-read is invoked.
    """
    await redis.set(notification_unread_count_key(user_id), 0)
    log.debug("notification_count_reset", user_id=user_id)


    # ══════════════════════════════════════════════════════════════════════════════
    #  Invalidation pattern reference
    # ══════════════════════════════════════════════════════════════════════════════

    """
    PATTERN ASSIGNMENT REFERENCE
    ═════════════════════════════════════════════════════════════════════════════

    Cache key                   Invalidation strategy      Event trigger
    ───────────────────────────────────────────────────────────────────────────
    user:<uid>                  Event + TTL (1 hr)          Profile edit, delete
    uname:<username>            Event + TTL (1 hr)          Username change
    uname_cd:<uid>              TTL-only (30 days)          Username change sets key
    presence:<uid>              TTL-only (60 s sliding)     WS heartbeat refreshes
    last_seen:<uid>             Event + TTL (7 days)        WS disconnect writes
    dau:<date>                  TTL-only (48 hr)            Auto-expiry is fine
    dur:<uid>:<date>            TTL-only (48 hr)            Auto-expiry is fine
    chat_p:<cid>                Event + TTL (30 min)        Add/remove participant
    chat_list:<uid>             Event + TTL (30 min)        Join/leave chat
    unread:<uid>:<cid>          Event (no TTL)              Mark-as-read, new message
    total_unread:<uid>          Event (no TTL)              Mark-as-read, new message
    last_read:<uid>:<cid>       Event + TTL (30 min)        Mark-as-read
    post:<pid>                  Event + TTL (15 min)        Edit, delete
    likes:<pid>                 Event (no TTL, Celery sync) Never evicted, synced
    liked:<uid>:<pid>           TTL-only (5 min)            Idempotency window only
    fc:<uid>                    Event (no TTL, Celery sync) Follow/unfollow
    fg:<uid>                    Event (no TTL, Celery sync) Follow/unfollow
    notif_unread:<uid>          Event (no TTL)              Create/read notification
    notif_idem:<hash>           TTL-only (60 s)             Dedup window only
    ws_conn:<uid>               Event + TTL (60 s sliding)  WS connect/disconnect
    search:<hash>:<uid>         TTL-only (30 s)             Short TTL sufficient
    rl:<action>:<id>            TTL-only (bucket TTL)       Managed by Lua script
    idem:<uuid>                 TTL-only (24 hr)            Process/store lifecycle
    bl:<jti>                    TTL-only (token lifetime)   Auto-expires with token
    rt_family:<uuid>            TTL-only (30 days)          Refreshed on rotation
    verify:<uid>                TTL-only (10 min)           Code expires naturally
    verify_cd:<uid>             TTL-only (60 s)             Cooldown expires naturally

    Legend:
        Event + TTL  — Deleted on change event. TTL is a safety net.
        Event only   — Deleted on change. No TTL (counter or permanent state).
        TTL-only     — No explicit delete. Expiry is the invalidation mechanism.
        Celery sync  — Counter stays in Redis indefinitely, synced to DB periodically.
        """