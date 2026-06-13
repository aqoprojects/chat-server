from __future__ import annotations

import asyncio
import structlog
from typing import Any

log = structlog.get_logger(__name__)


async def log_async(
    level: str,
    event: str,
    **kwargs: Any,
) -> None:
    """
    Emit a structlog event from an async context without blocking.

    This is a convenience wrapper — standard structlog calls are already
    async-safe in this project because we only write to stdout via
    StreamHandler. Use this when you want to be explicit or when emitting
from a coroutine that will be moved to run_in_executor in future.

Args:
    level:   "debug" | "info" | "warning" | "error" | "critical"
    event:   The event name string (the "event" field in the log).
    **kwargs: Additional key-value pairs merged into the log event.

    Example:
        await log_async("info", "message_delivered", chat_id=chat_id, user_id=user_id)
        """
    bound_log = log.bind(**kwargs)
    log_method = getattr(bound_log, level.lower(), bound_log.info)
    log_method(event)


def log_from_sync(
    level: str,
    event: str,
    loop: asyncio.AbstractEventLoop | None = None,
    **kwargs: Any,
) -> None:
    """
    Emit a structlog event from synchronous code running inside a Celery
    task or a script that has no async context.

    Celery workers run in their own thread pool — they cannot await
    coroutines. This function uses structlog's sync API directly, which
    is safe because Celery tasks do not share the FastAPI event loop.

    Args:
        level:   "debug" | "info" | "warning" | "error" | "critical"
        event:   The event name string.
        loop:    Unused — kept for API compatibility. Celery tasks never
        need to schedule into the FastAPI event loop.
        **kwargs: Additional key-value pairs merged into the log event.

        Example (inside a Celery task):
            log_from_sync("info", "email_sent", user_id=user_id, template="verification")
            """
    bound_log = log.bind(**kwargs)
    log_method = getattr(bound_log, level.lower(), bound_log.info)
    log_method(event)


class AsyncSafeLoggerMixin:
    """
    Mixin for service classes that need structured logging with guaranteed
    async safety. Provides self.log bound with the class name as logger.

    Usage:
class ChatService(AsyncSafeLoggerMixin):
    async def send_message(self, ...):
        self.log.info("message_queued", chat_id=str(chat_id))
        """

    @property
    def log(self) -> structlog.BoundLogger:
        if not hasattr(self, "_log"):
            object.__setattr__(
                self,
                "_log",
                structlog.get_logger(
                    f"{self.__class__.__module__}.{self.__class__.__name__}"
                ),
            )
        return self._log  # type: ignore[return-value]