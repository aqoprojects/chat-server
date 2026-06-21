from __future__ import annotations

from kombu import Exchange, Queue

# ══════════════════════════════════════════════════════════════════════════════
#  Exchange definitions
# ══════════════════════════════════════════════════════════════════════════════
#
#  An exchange is a RabbitMQ routing hub. Messages are published to an
#  exchange with a routing key. The exchange routes them to bound queues.
#
#  Exchange type "direct":
#      Message routing_key must exactly match the queue binding key.
#      Each queue receives only the messages addressed to it.
#      Most predictable for task routing — no wildcard fan-out.
#
#  durable=True:
#      Exchange survives RabbitMQ restart. Non-durable exchanges are lost
#      on restart — all un-consumed messages in bound queues are discarded.

CHATSERVER_EXCHANGE = Exchange(
    name="chatserver",
    type="direct",
    durable=True,
)

# Dead-letter exchange: tasks that have exhausted retries or exceeded
# their TTL are published here instead of being silently dropped.
DLX_EXCHANGE = Exchange(
    name="chatserver.dlx",
    type="direct",
    durable=True,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Queue definitions
# ══════════════════════════════════════════════════════════════════════════════
#
#  Each queue has:
#      name        : Queue name in RabbitMQ
#      exchange    : Which exchange it is bound to
#      routing_key : The key that routes messages from the exchange to this queue
#      durable     : Survives RabbitMQ restart
#      queue_arguments: RabbitMQ-specific queue settings (TTL, DLX, etc.)
#
#  Dead-letter arguments on each queue:
#      x-dead-letter-exchange  : Where to send rejected/expired messages
#      x-dead-letter-routing-key: Routing key on the dead-letter exchange
#      x-message-ttl           : Message TTL in milliseconds.
#                                 Messages older than this are dead-lettered.
#                                 Prevents stale tasks from being executed
#                                 long after the triggering event (e.g. a
#                                 verification email sent 24 hours late).

# ── email_queue ────────────────────────────────────────────────────────────────
# Sends verification emails, welcome emails, password reset emails.
# Priority: high — users are waiting for their verification code.
# TTL: 1 hour (3600000 ms) — a verification email older than 1 hour is
# pointless (the code has expired). Dead-letter it instead.
EMAIL_QUEUE = Queue(
    name="email_queue",
    exchange=CHATSERVER_EXCHANGE,
    routing_key="email",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange":   "chatserver.dlx",
        "x-dead-letter-routing-key": "email.dead",
        "x-message-ttl":            3_600_000,    # 1 hour in ms
        "x-max-priority":           10,           # enable priority levels
    },
)

# ── push_queue ─────────────────────────────────────────────────────────────────
# Sends offline push notifications via FCM / APNs.
# Priority: medium — push for a message sent 10 minutes ago is still useful.
# TTL: 24 hours (86400000 ms) — daily notification summaries are still useful.
PUSH_QUEUE = Queue(
    name="push_queue",
    exchange=CHATSERVER_EXCHANGE,
    routing_key="push",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange":    "chatserver.dlx",
        "x-dead-letter-routing-key": "push.dead",
        "x-message-ttl":             86_400_000,   # 24 hours in ms
        "x-max-priority":            5,
    },
)

# ── moderation_queue ───────────────────────────────────────────────────────────
# Content moderation analysis on messages and posts.
# Priority: low — async analysis, no user is waiting synchronously.
# TTL: 6 hours (21600000 ms) — content older than 6 hours is already visible;
# moderation is still valuable for pattern analysis but deprioritised.
MODERATION_QUEUE = Queue(
    name="moderation_queue",
    exchange=CHATSERVER_EXCHANGE,
    routing_key="moderation",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange":    "chatserver.dlx",
        "x-dead-letter-routing-key": "moderation.dead",
        "x-message-ttl":             21_600_000,   # 6 hours in ms
        "x-max-priority":            3,
    },
)

# ── media_queue ────────────────────────────────────────────────────────────────
# Image resizing (avatar thumbnails), file validation, cascade deletes.
# Priority: medium — avatar processing should complete before the user
# refreshes their profile.
# TTL: 2 hours — stale resize jobs for deleted users are pointless.
MEDIA_QUEUE = Queue(
    name="media_queue",
    exchange=CHATSERVER_EXCHANGE,
    routing_key="media",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange":    "chatserver.dlx",
        "x-dead-letter-routing-key": "media.dead",
        "x-message-ttl":             7_200_000,    # 2 hours in ms
        "x-max-priority":            5,
    },
)

# ── stream_queue ───────────────────────────────────────────────────────────────
# Redis Stream maintenance: XTRIM, XPENDING monitoring, dead-letter notifications.
# Priority: low — maintenance tasks run on schedule, not on user action.
# TTL: 1 hour — if a trimming task is delayed more than 1 hour, the next
# beat tick will issue a fresh one; the old task is obsolete.
STREAM_QUEUE = Queue(
    name="stream_queue",
    exchange=CHATSERVER_EXCHANGE,
    routing_key="stream",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange":    "chatserver.dlx",
        "x-dead-letter-routing-key": "stream.dead",
        "x-message-ttl":             3_600_000,    # 1 hour in ms
    },
)

# ── Dead-letter queues ─────────────────────────────────────────────────────────
# One DLQ per application queue.
# Tasks land here when they exceed their TTL or exhaust all retries.
# An ops engineer reviews DLQ contents to identify systematic failures.
# DLQ messages never expire — they persist until manually acknowledged
# or purged after investigation.

EMAIL_DLQ = Queue(
    name="email_queue.dead",
    exchange=DLX_EXCHANGE,
    routing_key="email.dead",
    durable=True,
)

PUSH_DLQ = Queue(
    name="push_queue.dead",
    exchange=DLX_EXCHANGE,
    routing_key="push.dead",
    durable=True,
)

MODERATION_DLQ = Queue(
    name="moderation_queue.dead",
    exchange=DLX_EXCHANGE,
    routing_key="moderation.dead",
    durable=True,
)

MEDIA_DLQ = Queue(
    name="media_queue.dead",
    exchange=DLX_EXCHANGE,
    routing_key="media.dead",
    durable=True,
)

STREAM_DLQ = Queue(
    name="stream_queue.dead",
    exchange=DLX_EXCHANGE,
    routing_key="stream.dead",
    durable=True,
)

# ── All queues — passed to Celery config ──────────────────────────────────────
ALL_QUEUES: tuple[Queue, ...] = (
    EMAIL_QUEUE,
    PUSH_QUEUE,
    MODERATION_QUEUE,
    MEDIA_QUEUE,
    STREAM_QUEUE,
    EMAIL_DLQ,
    PUSH_DLQ,
    MODERATION_DLQ,
    MEDIA_DLQ,
    STREAM_DLQ,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Task routing rules
# ══════════════════════════════════════════════════════════════════════════════
#
#  Maps task module paths to their target queue and routing key.
#  Used by app.conf.task_routes in workers/celery_app.py.
#
#  Format:
    #      "module.path.task_name": {
        #          "queue":       "<queue_name>",
        #          "routing_key": "<routing_key>",
        #      }
        #
        #  Wildcard pattern:
            #      "workers.tasks.email_tasks.*" routes ALL tasks in email_tasks.py
            #      to email_queue. Explicit task names override wildcards.
            #
            #  Priority override:
                #      Individual task dispatches can override priority at call time:
                    #          send_verification_email.apply_async(args=[...], priority=9)
                    #      The queue's x-max-priority setting must be >= the requested priority.

TASK_ROUTES: dict[str, dict[str, str]] = {

    # ── Email tasks ───────────────────────────────────────────────────────────
    "workers.tasks.email_tasks.send_verification_email": {
        "queue":       "email_queue",
        "routing_key": "email",
    },
    "workers.tasks.email_tasks.send_welcome_email": {
        "queue":       "email_queue",
        "routing_key": "email",
    },
    "workers.tasks.email_tasks.send_password_reset_email": {
        "queue":       "email_queue",
        "routing_key": "email",
    },

    # ── Push notification tasks ───────────────────────────────────────────────
    "workers.tasks.push_tasks.send_push_notification": {
        "queue":       "push_queue",
        "routing_key": "push",
    },
    "workers.tasks.push_tasks.send_bulk_push_notifications": {
        "queue":       "push_queue",
        "routing_key": "push",
    },
    "workers.tasks.push_tasks.retry_failed_push_notifications": {
        "queue":       "push_queue",
        "routing_key": "push",
    },

    # ── Media processing tasks ────────────────────────────────────────────────
    "workers.tasks.media_tasks.process_avatar_upload": {
        "queue":       "media_queue",
        "routing_key": "media",
    },
    "workers.tasks.media_tasks.generate_avatar_thumbnails": {
        "queue":       "media_queue",
        "routing_key": "media",
    },
    "workers.tasks.media_tasks.delete_user_media_files": {
        "queue":       "media_queue",
        "routing_key": "media",
    },
    "workers.tasks.media_tasks.delete_message_attachment": {
        "queue":       "media_queue",
        "routing_key": "media",
    },

    # ── Content moderation tasks ──────────────────────────────────────────────
    "workers.tasks.moderation_tasks.moderate_message_content": {
        "queue":       "moderation_queue",
        "routing_key": "moderation",
    },
    "workers.tasks.moderation_tasks.moderate_post_content": {
        "queue":       "moderation_queue",
        "routing_key": "moderation",
    },
    "workers.tasks.moderation_tasks.review_flagged_content": {
        "queue":       "moderation_queue",
        "routing_key": "moderation",
    },

    # ── Redis Stream maintenance tasks ────────────────────────────────────────
    "workers.tasks.stream_tasks.trim_chat_streams": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.monitor_pending_messages": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.reclaim_stuck_messages": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.cleanup_notification_streams": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },

    # ── Maintenance / cleanup tasks ───────────────────────────────────────────
    # These run via beat and go to stream_queue (low-priority, scheduled)
    "workers.tasks.stream_tasks.cleanup_expired_tokens": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.sync_counter_to_db": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.purge_old_notifications": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
    "workers.tasks.stream_tasks.health_check": {
        "queue":       "stream_queue",
        "routing_key": "stream",
    },
}



# ══════════════════════════════════════════════════════════════════════════════
#  Dead-letter queue monitoring
# ══════════════════════════════════════════════════════════════════════════════

async def get_dlq_depths() -> dict[str, int]:
    """
    Query the RabbitMQ management API for DLQ message counts.

    Returns a dict mapping DLQ name → message count.
    Called by the /admin/queues health endpoint (future Phase 7).

    A non-zero DLQ depth is an alert signal — tasks are failing
    permanently and require manual investigation.

    Returns empty dict if the management API is unreachable.
    """
    import httpx
    from core.config import settings

    dlq_names = [
        "email_queue.dead",
        "push_queue.dead",
        "moderation_queue.dead",
        "media_queue.dead",
        "stream_queue.dead",
    ]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            depths: dict[str, int] = {}
            for queue_name in dlq_names:
                url = (
                    f"{settings.rabbitmq_management_url}/api/queues"
                    f"/{settings.rabbitmq_vhost}/{queue_name}"
                )
                resp = await client.get(
                    url,
                    auth=(
                        settings.rabbitmq_management_user,
                        settings.rabbitmq_management_password,
                    ),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    depths[queue_name] = data.get("messages", 0)
                else:
                    depths[queue_name] = -1   # -1 = unknown
            return depths

    except Exception as exc:
        import structlog as _log
        _log.get_logger(__name__).warning(
            "dlq_depth_check_failed", error=str(exc)
        )
        return {}