from __future__ import annotations

import structlog
from celery import Celery
from celery.signals import setup_logging, worker_ready, worker_shutdown

from core.config import settings

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Celery application factory
# ══════════════════════════════════════════════════════════════════════════════

def create_celery_app() -> Celery:
    """
    Construct and return a fully configured Celery application instance.

    Called once at module level (bottom of this file) to produce the
    singleton `celery_app` object. Both the FastAPI process (for task
    dispatch) and the Celery worker process (for task execution) import
    this object.

    Configuration is read entirely from core.config.settings so no
    Celery configuration is hardcoded in this file.
    """
    app = Celery("chatserver")

    # ── Broker and result backend ─────────────────────────────────────────────
    app.conf.broker_url            = settings.celery_broker_url
    app.conf.result_backend        = settings.celery_result_backend

    # ── Serialization ─────────────────────────────────────────────────────────
    # JSON serializer only — never pickle.
    # Pickle deserialization can execute arbitrary code if a malicious
    # task payload is injected into the broker queue.
    app.conf.task_serializer       = settings.celery_task_serializer
    app.conf.result_serializer     = settings.celery_result_serializer
    app.conf.accept_content        = list(settings.celery_accept_content)

    # ── Task execution settings ───────────────────────────────────────────────
    # task_always_eager: run tasks synchronously in the calling process.
    # True in test — eliminates broker dependency in CI.
    app.conf.task_always_eager     = settings.is_test

    # task_eager_propagates: in eager mode, re-raise task exceptions
    # instead of catching them. Makes test failures visible immediately.
    app.conf.task_eager_propagates = settings.is_test

    # task_acks_late: acknowledge the task AFTER it completes, not when
    # it is received. If the worker crashes mid-task, the task is
    # re-queued automatically.
    app.conf.task_acks_late        = True

    # task_reject_on_worker_lost: if the worker process is killed while
    # executing a task (OOM kill, SIGKILL), requeue the task rather than
    # acknowledging it silently.
    app.conf.task_reject_on_worker_lost = True

    # worker_prefetch_multiplier: how many tasks a worker prefetches per
    # process. 1 = one task at a time. Prevents a slow task from blocking
    # faster tasks in the same worker process.
    # For long-running tasks (email, push), 1 is the correct value.
    app.conf.worker_prefetch_multiplier = 1

    # task_soft_time_limit: SIGTERM sent to the task after this many seconds.
    # The task gets a SoftTimeLimitExceeded exception to clean up.
    app.conf.task_soft_time_limit  = 300   # 5 minutes

    # task_time_hard_limit: SIGKILL sent after this many seconds regardless.
    # task_reject_on_worker_lost handles the requeue.
    app.conf.task_time_limit       = 360   # 6 minutes

    # ── Result settings ───────────────────────────────────────────────────────
    # Store task results only for tasks that explicitly need them.
    # Most fire-and-forget tasks (email, push) do not need result storage.
    app.conf.task_ignore_result    = True   # default: ignore results
    app.conf.result_expires        = 3600   # 1 hour TTL on stored results

    # ── Timezone ──────────────────────────────────────────────────────────────
    app.conf.timezone              = "UTC"
    app.conf.enable_utc            = True

    # ── Worker concurrency ────────────────────────────────────────────────────
    app.conf.worker_concurrency    = settings.celery_worker_concurrency

    # ── Task autodiscovery ────────────────────────────────────────────────────
    # Celery discovers tasks in workers/tasks/*.py automatically.
    # The include list must match the actual module paths.
    app.conf.include = [
        "workers.tasks.email_tasks",
        "workers.tasks.push_tasks",
        "workers.tasks.media_tasks",
        "workers.tasks.moderation_tasks",
        "workers.tasks.stream_tasks",
    ]

    # ── Task routing ──────────────────────────────────────────────────────────
    # Imported from workers/queues.py — defined in Topic 3.
    from workers.queues import TASK_ROUTES
    app.conf.task_routes = TASK_ROUTES

    # ── Beat schedule ─────────────────────────────────────────────────────────
    # Imported from workers/beat_schedule.py — defined in Topic 4.
    from workers.beat_schedule import BEAT_SCHEDULE
    app.conf.beat_schedule = BEAT_SCHEDULE

    # ── Dead-letter queue config ──────────────────────────────────────────────
    # Configured via broker transport options (RabbitMQ-specific).
    # Defined in Topic 5.
    app.conf.broker_transport_options = _build_broker_transport_options()

    return app


def _build_broker_transport_options() -> dict:
    """
    RabbitMQ-specific broker transport options.

    These settings configure:
        - Connection heartbeat: keeps AMQP connections alive through
        firewalls and NAT mappings.
        - Max retries: how many times Celery retries connecting to the
        broker before giving up.
        - Retry interval: seconds between connection retry attempts.
        - Confirm publish: wait for broker to confirm message receipt
        before returning from task.delay(). Slightly slower but prevents
        message loss if the broker crashes immediately after receipt.
        """
    return {
        # Heartbeat interval in seconds.
        # Must be shorter than any firewall/NAT idle timeout.
        # 120 seconds is a safe value for most cloud environments.
        "heartbeat": 120,

        # Retry connecting to broker up to 5 times before failing.
        "max_retries": 5,

        # Wait 2 seconds between retry attempts, with exponential backoff.
        "interval_start": 2,
        "interval_step":  2,
        "interval_max":   30,

        # Confirm that the broker received the message before returning.
        # Uses RabbitMQ publisher confirms (AMQP confirm mode).
        "confirm_publish": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Logging integration — prevent Celery from overwriting structlog
# ══════════════════════════════════════════════════════════════════════════════

# @setup_logging.connect
# def configure_celery_logging(**kwargs: object) -> None:
#     """
#     Suppress Celery's default logging configuration.

#     Celery connects to this signal during worker startup and calls
#     logging.config.dictConfig() with its own formatter — overwriting
#     the structlog pipeline configured in core/logging/setup.py.

#     By connecting here and doing nothing, we tell Celery "logging is
#     already configured — leave it alone." Our structlog pipeline remains
#     intact across the full worker process lifetime.
#     """
#     pass   # intentionally empty


# ══════════════════════════════════════════════════════════════════════════════
#  Worker lifecycle signals
# ══════════════════════════════════════════════════════════════════════════════

@worker_ready.connect
def on_worker_ready(**kwargs: object) -> None:
    """Log a structured event when the Celery worker is fully started."""
    log.info(
        "celery_worker_ready",
        broker=settings.celery_broker_url.split("@")[-1],   # hide credentials
        concurrency=settings.celery_worker_concurrency,
        env=settings.app_env,
    )


@worker_shutdown.connect
def on_worker_shutdown(**kwargs: object) -> None:
    """Log a structured event when the Celery worker is shutting down."""
    log.info("celery_worker_shutdown")
    

    # ══════════════════════════════════════════════════════════════════════════════
    #  Module-level singleton
    # ══════════════════════════════════════════════════════════════════════════════

# This is the object referenced by the Celery CLI:
#   celery -A workers.celery_app worker
#   celery -A workers.celery_app beat
#
# FastAPI imports it for task dispatch:
#   from workers.celery_app import celery_app
#   celery_app.send_task("workers.tasks.email_tasks.send_verification_email", ...)

celery_app: Celery = create_celery_app()