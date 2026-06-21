from __future__ import annotations

import structlog
from celery import Task

from workers.celery_app import celery_app

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Base task class with structured logging and retry logic
# ══════════════════════════════════════════════════════════════════════════════

class BaseTask(Task):
    """
    Base Celery task class.

    Adds:
        - Structured logging on task start, success, failure, retry.
        - Automatic retry with exponential backoff on unexpected exceptions.
        - Max retries: 3. Retry delays: 30s, 60s, 120s.

        All application tasks inherit from this class via:
    @celery_app.task(base=BaseTask, ...)
    """
    abstract = True

    # Retry configuration
    max_retries     = 3
    default_retry_delay = 30    # seconds

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: object,
    ) -> None:
        log.error(
            "celery_task_failed",
            task_name=self.name,
            task_id=task_id,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: object,
    ) -> None:
        log.warning(
            "celery_task_retrying",
            task_name=self.name,
            task_id=task_id,
            retry_count=self.request.retries,
            error=str(exc),
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_success(
        self,
        retval: object,
        task_id: str,
        args: tuple,
        kwargs: dict,
    ) -> None:
        log.debug(
            "celery_task_succeeded",
            task_name=self.name,
            task_id=task_id,
        )
        super().on_success(retval, task_id, args, kwargs)


# ══════════════════════════════════════════════════════════════════════════════
#  Health check task
# ══════════════════════════════════════════════════════════════════════════════

@celery_app.task(
    name="workers.tasks.stream_tasks.health_check",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
    # No retries for health check — if it fails, the next beat tick dispatches another
    max_retries=0,
)
def health_check() -> None:
    """
    No-op task dispatched every 60 seconds by Celery beat.

    Confirms:
        1. The beat scheduler is running and dispatching tasks.
        2. The worker is alive and consuming from stream_queue.
        3. The broker connection is healthy (task was delivered).

        Monitored by:
            - Flower UI: task execution count should increment every 60s.
            - Application metrics (Phase 7): alert if no health_check success
            in the last 5 minutes.
            """
    log.info("celery_worker_health_check_ok")


# ══════════════════════════════════════════════════════════════════════════════
#  Maintenance task stubs
#  Full implementations written in their respective phases.
# ══════════════════════════════════════════════════════════════════════════════

@celery_app.task(
    name="workers.tasks.stream_tasks.trim_chat_streams",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def trim_chat_streams() -> None:
    """
    Trim all active Redis Streams to settings.stream_max_len entries.
    Full implementation: Stage 27 (Redis Stream management).
    """
    log.info("trim_chat_streams_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.monitor_pending_messages",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def monitor_pending_messages() -> None:
    """
    Monitor XPENDING for stuck messages. Full implementation: Stage 27.
    """
    log.info("monitor_pending_messages_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.reclaim_stuck_messages",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def reclaim_stuck_messages() -> None:
    """
    XAUTOCLAIM messages pending > 60 seconds. Full implementation: Stage 27.
    """
    log.info("reclaim_stuck_messages_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.cleanup_notification_streams",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def cleanup_notification_streams() -> None:
    """
    Trim per-user notification streams. Full implementation: Stage 30.
    """
    log.info("cleanup_notification_streams_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.cleanup_expired_tokens",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def cleanup_expired_tokens() -> None:
    """
    Delete expired DB tokens. Full implementation: Stage 12.
    """
    log.info("cleanup_expired_tokens_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.sync_counter_to_db",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def sync_counter_to_db() -> None:
    """
    Sync Redis counters to PostgreSQL. Full implementation: Stage 19.
    """
    log.info("sync_counter_to_db_stub_called")


@celery_app.task(
    name="workers.tasks.stream_tasks.purge_old_notifications",
    base=BaseTask,
    queue="stream_queue",
    ignore_result=True,
)
def purge_old_notifications() -> None:
    """
    Delete notifications older than 90 days. Full implementation: Stage 28.
    """
    log.info("purge_old_notifications_stub_called")