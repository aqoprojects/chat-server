from __future__ import annotations

from celery.schedules import crontab

# ══════════════════════════════════════════════════════════════════════════════
#  Celery Beat Periodic Task Schedule
# ══════════════════════════════════════════════════════════════════════════════
#
#  All times are UTC (app.conf.enable_utc = True in celery_app.py).
#
#  Schedule format options:
    #      timedelta(seconds=N)          — run every N seconds
    #      crontab(minute="*/5")         — run every 5 minutes (cron syntax)
    #      crontab(hour=2, minute=0)     — run at 02:00 UTC every day
    #
    #  Each entry:
        #      "task"    : Fully qualified task module path
        #      "schedule": How often to run
        #      "args"    : Positional arguments (list) — optional
        #      "kwargs"  : Keyword arguments (dict) — optional
        #      "options" : Task options — queue, priority, expires
        #
        #  expires: If the beat scheduler falls behind (e.g. broker is down) and
        #  queues up many copies of the same periodic task, `expires` ensures
        #  old copies are discarded once their window has passed. This prevents
        #  a "thundering herd" of maintenance tasks executing simultaneously
        #  after a broker restart.

from datetime import timedelta

BEAT_SCHEDULE: dict[str, dict] = {

    # ══════════════════════════════════════════════════════════════════════════
    #  Worker health check — every 60 seconds
    #  Dispatches a no-op task to confirm the worker is alive and consuming.
    # ══════════════════════════════════════════════════════════════════════════
    "worker-health-check": {
        "task":     "workers.tasks.stream_tasks.health_check",
        "schedule": timedelta(seconds=60),
        "options":  {
            "queue":   "stream_queue",
            "expires": 55,   # discard if not consumed within 55s
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Redis Stream trimming — every 10 minutes
    #  Trims all active chat streams to settings.stream_max_len entries.
    #  Prevents unbounded stream growth.
    # ══════════════════════════════════════════════════════════════════════════
    "trim-chat-streams": {
        "task":     "workers.tasks.stream_tasks.trim_chat_streams",
        "schedule": timedelta(minutes=10),
        "options":  {
            "queue":   "stream_queue",
            "expires": 540,   # 9 minutes — discard if previous run still pending
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Redis Stream pending message monitor — every 5 minutes
    #  Checks XPENDING for messages stuck in processing state.
    #  Claims and re-delivers messages pending > 30 seconds.
    # ══════════════════════════════════════════════════════════════════════════
    "monitor-pending-stream-messages": {
        "task":     "workers.tasks.stream_tasks.monitor_pending_messages",
        "schedule": timedelta(minutes=5),
        "options":  {
            "queue":   "stream_queue",
            "expires": 240,   # 4 minutes
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Notification stream cleanup — every 30 minutes
    #  Trims per-user notification streams to max 1000 entries.
    # ══════════════════════════════════════════════════════════════════════════
    "cleanup-notification-streams": {
        "task":     "workers.tasks.stream_tasks.cleanup_notification_streams",
        "schedule": timedelta(minutes=30),
        "options":  {
            "queue":   "stream_queue",
            "expires": 1500,   # 25 minutes
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Expired token cleanup — every hour
    #  Deletes expired verification tokens, blacklisted tokens,
    #  and revoked refresh tokens from the database.
    # ══════════════════════════════════════════════════════════════════════════
    "cleanup-expired-tokens": {
        "task":     "workers.tasks.stream_tasks.cleanup_expired_tokens",
        "schedule": crontab(minute=0),   # top of every hour
        "options":  {
            "queue":   "stream_queue",
            "expires": 3300,   # 55 minutes — discard if not run within the hour
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Redis counter sync to PostgreSQL — every 15 minutes
    #  Syncs: like_count, follower_count, following_count, post_count
    #  from Redis INCR/DECR counters back to the corresponding DB columns.
    # ══════════════════════════════════════════════════════════════════════════
    "sync-counters-to-db": {
        "task":     "workers.tasks.stream_tasks.sync_counter_to_db",
        "schedule": timedelta(minutes=15),
        "options":  {
            "queue":   "stream_queue",
            "expires": 840,   # 14 minutes
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Stale push notification retry — every hour
    #  Finds notifications with push_sent=false that are > 5 minutes old
    #  and retries delivery. Catches failures from FCM/APNs transient errors.
    # ══════════════════════════════════════════════════════════════════════════
    "retry-failed-push-notifications": {
        "task":     "workers.tasks.push_tasks.retry_failed_push_notifications",
        "schedule": crontab(minute=30),   # 30 minutes past every hour
        "options":  {
            "queue":   "push_queue",
            "expires": 3300,
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Old notification purge — daily at 03:00 UTC
    #  Deletes notifications older than 90 days.
    #  Low-traffic time: minimises DB lock contention with user traffic.
    # ══════════════════════════════════════════════════════════════════════════
    "purge-old-notifications": {
        "task":     "workers.tasks.stream_tasks.purge_old_notifications",
        "schedule": crontab(hour=3, minute=0),
        "options":  {
            "queue":   "stream_queue",
            "expires": 82800,   # 23 hours
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    #  Stuck message reclaim — every 2 minutes
    #  Uses XAUTOCLAIM to reclaim Redis Stream messages that have been
    #  in pending state for > 60 seconds (worker may have crashed).
    # ══════════════════════════════════════════════════════════════════════════
    "reclaim-stuck-stream-messages": {
        "task":     "workers.tasks.stream_tasks.reclaim_stuck_messages",
        "schedule": timedelta(minutes=2),
        "options":  {
            "queue":   "stream_queue",
            "expires": 110,   # just under 2 minutes
        },
    },
}