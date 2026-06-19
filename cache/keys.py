from __future__ import annotations

"""
Redis key builders for all application namespaces.

Naming convention:
<prefix>:<identifier>[:<sub-identifier>]

All prefixes are defined in core.config.settings and read here.
This file is the single source of truth for every Redis key the
application uses. Never construct a Redis key string outside this file.
"""

from core.config import settings

# ══════════════════════════════════════════════════════════════════════════════
#  Rate limiting
# ══════════════════════════════════════════════════════════════════════════════


def rate_limit_key(action: str, identifier: str) -> str:
    """
    Token bucket key for a specific action + identifier combination.

    Args:
        action:     Short label for the endpoint being limited.
        e.g. "register", "login", "post_create"
        identifier: The value being rate-limited.
        For unauthenticated endpoints: the client IP address.
        For authenticated endpoints: the user_id (UUID string).

        Examples:
            rate_limit_key("register", "192.168.1.1")
            → "rl:register:192.168.1.1"

            rate_limit_key("login", "192.168.1.1")
            → "rl:login:192.168.1.1"

            rate_limit_key("post_create", "a1b2c3d4-...")
            → "rl:post_create:a1b2c3d4-..."
    """
    return f"{settings.rate_limit_key_prefix}{action}:{identifier}"


def rate_limit_chat_key(action: str, user_id: str, chat_id: str) -> str:
    """
    Per-chat token bucket key for message sending rate limits.

    Used for the per-chat-per-user rate limit (distinct from the
    global per-user message rate limit).

    Example:
        rate_limit_chat_key("msg", "user-uuid", "chat-uuid")
        → "rl:msg:user-uuid:chat-uuid"
    """
    return f"{settings.rate_limit_key_prefix}{action}:{user_id}:{chat_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Idempotency
# ══════════════════════════════════════════════════════════════════════════════


def idempotency_key(idempotency_id: str) -> str:
    """
    Key for storing the cached response of an idempotent request.

    The idempotency_id is supplied by the client in the
    X-Idempotency-Key header. It must be a UUID v4.

    Example:
        idempotency_key("550e8400-e29b-41d4-a716-446655440000")
        → "idem:550e8400-e29b-41d4-a716-446655440000"
    """
    return f"{settings.idempotency_key_prefix}{idempotency_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  JWT token blacklist
# ══════════════════════════════════════════════════════════════════════════════


def blacklist_key(jti: str) -> str:
    """
    Key for a blacklisted JWT access token.
    The key's TTL matches the token's remaining lifetime so Redis
    automatically evicts the entry when the token would have expired anyway.

    jti: JWT ID claim — a unique identifier per access token.

    Example:
        blacklist_key("abc123")
        → "bl:abc123"
    """
    return f"{settings.jwt_blacklist_prefix}{jti}"


def refresh_family_key(family_id: str) -> str:
    """
    Key for a refresh token family.
    Stores the latest refresh token ID in the family.
    Used for stolen token detection — if the stored ID differs from
    the presented token's ID, the family is revoked.

    Example:
        refresh_family_key("family-uuid")
        → "rt_family:family-uuid"
    """
    return f"{settings.jwt_refresh_family_prefix}{family_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Email verification
# ══════════════════════════════════════════════════════════════════════════════


def verification_code_key(user_id: str) -> str:
    """
    Stores the hashed verification code for a user awaiting email verification.
    TTL = settings.verification_code_ttl (600 seconds by default).

    Example:
        verification_code_key("user-uuid")
        → "verify:user-uuid"
    """
    return f"verify:{user_id}"


def verification_resend_key(user_id: str) -> str:
    """
    Cooldown key that prevents a user from requesting a new verification
    email too frequently. TTL = settings.verification_resend_cooldown.

    Example:
        verification_resend_key("user-uuid")
        → "verify_cd:user-uuid"
    """
    return f"verify_cd:{user_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  User cache
# ══════════════════════════════════════════════════════════════════════════════


def user_cache_key(user_id: str) -> str:
    """
    Full user profile cached as JSON.
    Invalidated on profile edit, avatar change, or account deletion.

    Example:
        user_cache_key("user-uuid")
        → "user:user-uuid"
    """
    return f"user:{user_id}"


def user_by_username_key(username: str) -> str:
    """
    Maps a username string to a user_id.
    Cached to avoid a DB lookup on username existence checks.

    Example:
        user_by_username_key("john_doe")
        → "uname:john_doe"
    """
    return f"uname:{username.lower()}"


def username_change_cooldown_key(user_id: str) -> str:
    """
    Cooldown key that enforces the 30-day username change restriction.
    TTL = settings.username_change_cooldown_days * 86400.

    Example:
        username_change_cooldown_key("user-uuid")
        → "uname_cd:user-uuid"
    """
    return f"{settings.username_change_key_prefix}{user_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Online presence & last seen
# ══════════════════════════════════════════════════════════════════════════════


def presence_key(user_id: str) -> str:
    """
    Exists (with sliding TTL) when the user is online.
    TTL = settings.presence_ttl (60 seconds by default).
    Refreshed on every WebSocket heartbeat/message.

    Example:
        presence_key("user-uuid")
        → "presence:user-uuid"
    """
    return f"{settings.presence_key_prefix}{user_id}"


def last_seen_key(user_id: str) -> str:
    """
    Stores the user's last-seen UTC timestamp as an ISO 8601 string.
    Written on WebSocket disconnect or when the presence key expires.

    Example:
        last_seen_key("user-uuid")
        → "last_seen:user-uuid"
    """
    return f"{settings.last_seen_key_prefix}{user_id}"


def dau_key(date_str: str) -> str:
    """
    Daily Active Users set for a specific date.
    A Redis SET where each member is a user_id.
    The date_str format is YYYY-MM-DD.

    Example:
        dau_key("2025-06-01")
        → "dau:2025-06-01"
    """
    return f"{settings.dau_key_prefix}{date_str}"


def user_online_duration_key(user_id: str, date_str: str) -> str:
    """
    Stores the total online duration (in seconds) for a user on a given day.
    Written on WebSocket disconnect: duration = disconnect_time - connect_time.

    Example:
        user_online_duration_key("user-uuid", "2025-06-01")
        → "dur:user-uuid:2025-06-01"
    """
    return f"dur:{user_id}:{date_str}"


# ══════════════════════════════════════════════════════════════════════════════
#  Chat & unread counts
# ══════════════════════════════════════════════════════════════════════════════


def chat_participants_key(chat_id: str) -> str:
    """
    Cached SET of participant user_ids for a chat.
    Used to enforce participant-only access without a DB query on
    every message send or WebSocket event.

    Example:
        chat_participants_key("chat-uuid")
        → "chat_p:chat-uuid"
    """
    return f"chat_p:{chat_id}"


def user_chat_list_key(user_id: str) -> str:
    """
    Cached list of chat_ids the user is a member of.
    Used on WebSocket connect to subscribe the user to all their streams.

    Example:
        user_chat_list_key("user-uuid")
        → "chat_list:user-uuid"
    """
    return f"chat_list:{user_id}"


def unread_count_key(user_id: str, chat_id: str) -> str:
    """
    Unread message count for a specific user in a specific chat.
    Incremented on new message delivery, reset to 0 on mark-as-read.

    Example:
        unread_count_key("user-uuid", "chat-uuid")
        → "unread:user-uuid:chat-uuid"
    """
    return f"unread:{user_id}:{chat_id}"


def total_unread_key(user_id: str) -> str:
    """
    Total unread count across all chats for a user.
    Sum of all unread_count_key values — maintained as a separate counter
    so the notification badge can be served with a single GET.

    Example:
        total_unread_key("user-uuid")
        → "total_unread:user-uuid"
    """
    return f"total_unread:{user_id}"


def last_read_message_key(user_id: str, chat_id: str) -> str:
    """
    The message_id of the last message the user has read in a chat.
    Used for offline catch-up: XRANGE stream_key last_read_id + to now.

    Example:
        last_read_message_key("user-uuid", "chat-uuid")
        → "last_read:user-uuid:chat-uuid"
    """
    return f"last_read:{user_id}:{chat_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Redis Streams
# ══════════════════════════════════════════════════════════════════════════════


def chat_stream_key(chat_id: str) -> str:
    """
    Redis Stream key for all message events in a specific chat.
    Each chat has its own stream so XTRIM operates per-chat.

    Example:
        chat_stream_key("chat-uuid")
        → "stream:chat:chat-uuid"
    """
    return f"stream:chat:{chat_id}"


def notification_stream_key(user_id: str) -> str:
    """
    Redis Stream key for all notification events for a specific user.
    Per-user streams keep notification fan-out isolated.

    Example:
        notification_stream_key("user-uuid")
        → "stream:notif:user-uuid"
    """
    return f"stream:notif:{user_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Posts & likes
# ══════════════════════════════════════════════════════════════════════════════


def post_cache_key(post_id: str) -> str:
    """
    Cached post data as JSON.
    Invalidated on edit or soft delete.

    Example:
        post_cache_key("post-uuid")
        → "post:post-uuid"
    """
    return f"post:{post_id}"


def post_like_count_key(post_id: str) -> str:
    """
    Like counter for a post stored as a Redis integer.
    Incremented/decremented atomically with INCR/DECR.
    Periodically synced back to PostgreSQL via a Celery beat task.

    Example:
        post_like_count_key("post-uuid")
        → "likes:post-uuid"
    """
    return f"likes:{post_id}"


def user_liked_post_key(user_id: str, post_id: str) -> str:
    """
    Flag indicating a specific user has liked a specific post.
    Used for idempotency on the like endpoint — prevents double-likes
    without a DB query.

    Example:
        user_liked_post_key("user-uuid", "post-uuid")
        → "liked:user-uuid:post-uuid"
    """
    return f"liked:{user_id}:{post_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Follower counts (Redis counters — periodically synced to DB)
# ══════════════════════════════════════════════════════════════════════════════


def follower_count_key(user_id: str) -> str:
    """
    Example:
        follower_count_key("user-uuid")
        → "fc:user-uuid"
    """
    return f"fc:{user_id}"


def following_count_key(user_id: str) -> str:
    """
    Example:
        following_count_key("user-uuid")
        → "fg:user-uuid"
    """
    return f"fg:{user_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Notifications
# ══════════════════════════════════════════════════════════════════════════════


def notification_unread_count_key(user_id: str) -> str:
    """
    Total unread notification count for a user.
    Incremented when a notification is created.
    Decremented when mark-as-read is called.
    Reset to 0 on mark-all-read.

    Served from Redis for the notification bell badge.
    Falls back to COUNT(*) FROM notifications WHERE
    recipient_id=$id AND is_read=false on cache miss.

    Example:
        notification_unread_count_key("user-uuid")
        → "notif_unread:user-uuid"
    """
    return f"notif_unread:{user_id}"


def notification_idempotency_key(
    recipient_id: str,
    notification_type: str,
    entity_id: str,
    actor_id: str,
) -> str:
    """
    Short-lived Redis key for notification deduplication.
    TTL = 60 seconds (the idempotency window).

    If this key exists in Redis, a duplicate notification was already
    created within the last 60 seconds and the new one is suppressed.

    The key is a SHA-256 hash of the four identifying fields,
    stored as a 64-character hex string — identical to the
    idempotency_key column in the notifications table.

    Example:
        notification_idempotency_key("uid", "mention", "msg-id", "actor-id")
        → "notif_idem:sha256hex..."
    """
    import hashlib

    raw = f"{recipient_id}:{notification_type}:{entity_id}:{actor_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"notif_idem:{digest}"


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket connection registry
# ══════════════════════════════════════════════════════════════════════════════


def ws_connection_key(user_id: str) -> str:
    """
    Tracks which server instance holds the user's active WebSocket connection.
    TTL = settings.presence_ttl (60 seconds), sliding — refreshed on heartbeat.
    Deleted immediately on WebSocket disconnect.

    Value: server instance identifier string ("local" in single-server dev,
    pod name or host:port in multi-server Kubernetes deployment).

    Example:
        ws_connection_key("user-uuid")
        → "ws_conn:user-uuid"
    """
    return f"ws_conn:{user_id}"


# ══════════════════════════════════════════════════════════════════════════════
#  Search result cache
# ══════════════════════════════════════════════════════════════════════════════


def search_cache_key(query: str, country: str, user_id: str) -> str:
    """
    Short-lived cache for user search results (30 second TTL).

    The cache key incorporates:
        query   — the search string (lowercased)
        country — the requesting user's country code (for location boosting)
        user_id — the requesting user (mutual-follow boost is user-specific)

        A 16-character hex prefix of the SHA-256 hash of (query + country)
        is used to keep the key short while avoiding collisions for different
        query strings.

        Example:
            search_cache_key("john", "NG", "user-uuid")
            → "search:a3f2b1c0d4e5f678:user-uuid"
    """


    import hashlib

    raw = f"{query.lower()}:{country.upper()}"
    query_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"search:{query_hash}:{user_id}"
