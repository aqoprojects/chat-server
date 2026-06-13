from __future__ import annotations

import logging
import logging.config
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from core.config import settings


# ══════════════════════════════════════════════════════════════════════════════
#  Custom processors
# ══════════════════════════════════════════════════════════════════════════════

def _add_app_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Inject static application-level fields into every log event.

    These fields appear in every single log line so that when you are
    searching ELK across multiple services or deployments, you can
    immediately filter to this application and environment.

    Fields added:
        app     — application name, always "chatserver"
        env     — APP_ENV value: development | test | production
        """
    event_dict["app"] = "chatserver"
    event_dict["env"] = settings.app_env
    return event_dict


def _reorder_keys(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Reorder keys in the event dict so the most important fields appear
    first in the JSON output. This makes log lines easier to scan in the
    terminal (when pretty-printed) and in ELK (when displayed as a table).

    Preferred order:
        timestamp, level, event, app, env, logger, request_id
        ... then all remaining context keys alphabetically.

        Python dicts preserve insertion order (3.7+), so this works
        by rebuilding the dict with the priority keys first.
        """
    priority_keys = [
        "timestamp",
        "level",
        "event",
        "app",
        "env",
        "logger",
        "request_id",
    ]

    reordered: EventDict = {}
    for key in priority_keys:
        if key in event_dict:
            reordered[key] = event_dict.pop(key)

    # Append remaining keys in their original order
    reordered.update(event_dict)
    return reordered


def _drop_color_message(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Remove the `color_message` key that uvicorn injects into its access
    log records. It contains ANSI escape codes that are meaningless in
    JSON output and pollute the ELK index.
    """
    event_dict.pop("color_message", None)
    return event_dict


def _stringify_exc_info(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    If exc_info is present, format the traceback as a single string
    under the key "exception" and remove the raw exc_info tuple.

    structlog's built-in format_exc_info processor does this for the
    ConsoleRenderer but not for JSONRenderer — we handle it uniformly
    here so both renderers get a clean string.
    """
    exc_info = event_dict.pop("exc_info", None)
    if exc_info:
        import traceback
        if exc_info is True:
            import sys
            exc_info = sys.exc_info()
        if exc_info[0] is not None:
            event_dict["exception"] = "".join(
                traceback.format_exception(*exc_info)
            ).strip()
    return event_dict


# ══════════════════════════════════════════════════════════════════════════════
#  Shared processor chain
#  These processors run for EVERY log event regardless of renderer.
# ══════════════════════════════════════════════════════════════════════════════

def _build_shared_processors() -> list[Any]:
    """
    Return the list of processors that run before the final renderer.

    Processor execution order (left to right):

        1.  merge_contextvars     — pull in any context bound via
        structlog.contextvars.bind_contextvars()
        (e.g. request_id bound by RequestIDMiddleware)

        2.  add_log_level         — add "level": "info" / "warning" / "error" etc.

        3.  add_logger_name       — add "logger": "app.api.v1.auth" etc.

        4.  _add_app_context      — inject app="chatserver", env="development"

        5.  TimeStamper           — add "timestamp": "2025-01-01T12:00:00.000Z"
        ISO 8601 UTC, millisecond precision.
        UTC is mandatory — mixing timezones in logs
        across servers is a debugging nightmare.

        6.  _drop_color_message   — strip uvicorn's ANSI color_message field

        7.  _stringify_exc_info   — format exception tracebacks as strings

        8.  StackInfoRenderer     — render stack_info if present (rare)

        9.  _reorder_keys         — put timestamp/level/event first

        The final renderer (JSON or Console) is appended per-environment
        in configure_logging() below.
        """
    return [
        # 1. Merge context variables (bound per-request by middleware)
        structlog.contextvars.merge_contextvars,

        # 2. Add log level string
        structlog.stdlib.add_log_level,

        # 3. Add the logger name (module path)
        structlog.stdlib.add_logger_name,

        # 4. Inject static app/env fields
        _add_app_context,

        # 5. UTC timestamp in ISO 8601 with millisecond precision
        structlog.processors.TimeStamper(fmt="iso", utc=True),

        # 6. Strip uvicorn's color_message
        _drop_color_message,

        # 7. Format exc_info tracebacks as strings
        _stringify_exc_info,

        # 8. Render stack_info if provided
        structlog.processors.StackInfoRenderer(),

        # 9. Reorder keys for readability
        _reorder_keys,
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  stdlib logging configuration
#  Intercepts all stdlib logging output (FastAPI, uvicorn, SQLAlchemy, etc.)
#  and routes it through the structlog processor chain.
# ══════════════════════════════════════════════════════════════════════════════

def _build_stdlib_logging_config(log_level: str, use_json: bool) -> dict[str, Any]:
    """
    Build a logging.config.dictConfig-compatible configuration dict.

    All stdlib loggers route through the "structlog" handler which
    passes records to structlog for processing. This means uvicorn's
    access logs, SQLAlchemy's SQL echo, and asyncpg's debug output
    all appear in the same structured format as your own log calls.

    Third-party loggers that are noisy in development are quieted
    by setting their level to WARNING or ERROR below.
    """
    renderer = structlog.dev.ConsoleRenderer(
    colors=True,
    exception_formatter=structlog.dev.plain_traceback,
    )
    return {
    "version": 1,
    # False: do not disable any loggers that were configured before
    # this call. This matters for libraries that configure their own
    # handlers at import time.
    "disable_existing_loggers": False,

    "formatters": {
        "structlog": {
            # ProcessorFormatter bridges stdlib → structlog.
            # It runs each stdlib LogRecord through the shared
            # processor chain before rendering.
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                # Extract stdlib-specific fields (filename, lineno, etc.)
                # and merge them into the structlog event dict.
               structlog.stdlib.ProcessorFormatter.remove_processors_meta,
               renderer,
            ],
            "foreign_pre_chain": _build_shared_processors(),
        }
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "structlog",
        }
    },

    "root": {
        # Root logger catches everything not explicitly configured below.
        "handlers": ["console"],
        "level": log_level,
    },

    "loggers": {
        # ── Application loggers ───────────────────────────────────────
        "app":      {"level": log_level, "propagate": True},
        "core":     {"level": log_level, "propagate": True},
        "db":       {"level": log_level, "propagate": True},
        "cache":    {"level": log_level, "propagate": True},
        "services": {"level": log_level, "propagate": True},
        "workers":  {"level": log_level, "propagate": True},

        # ── Uvicorn ───────────────────────────────────────────────────
        # uvicorn.access: HTTP access logs — INFO in dev so you see
        # every request; WARNING in prod (rely on load balancer logs).
        "uvicorn.access": {
            "level": "INFO" if not use_json else "WARNING",
            "propagate": True,
        },
        "uvicorn.error": {"level": "INFO", "propagate": True},

        # ── SQLAlchemy ────────────────────────────────────────────────
        # "sqlalchemy.engine" emits every SQL statement when echo=True.
        # In dev this is useful; in prod it floods the logs.
        "sqlalchemy.engine": {
            "level": "INFO" if getattr(settings, "db_echo_sql", False) else "WARNING",
            "propagate": True,
        },
        "sqlalchemy.pool": {"level": "WARNING", "propagate": True},

        # ── asyncpg ───────────────────────────────────────────────────
        "asyncpg": {"level": "WARNING", "propagate": True},

        # ── redis-py ──────────────────────────────────────────────────
        "redis": {"level": "WARNING", "propagate": True},

        # ── Celery ────────────────────────────────────────────────────
        "celery":          {"level": "INFO", "propagate": True},
        "celery.task":     {"level": "INFO", "propagate": True},
        "celery.worker":   {"level": "INFO", "propagate": True},

        # ── Alembic ───────────────────────────────────────────────────
        "alembic": {"level": "INFO", "propagate": True},

        # ── httpx (used for IP geolocation requests) ──────────────────
        "httpx":    {"level": "WARNING", "propagate": True},
        "httpcore": {"level": "WARNING", "propagate": True},
    },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Main configuration entry point
# ══════════════════════════════════════════════════════════════════════════════

def configure_logging() -> None:
    """
    Configure structlog and stdlib logging for the current environment.

    Must be called once, at the very beginning of create_app(), before
    any module has a chance to emit a log event. Subsequent calls are
    safe — structlog.configure() is idempotent.

    Environment behaviour:
        development — coloured, aligned ConsoleRenderer output to stdout.
        Human-readable. Not machine-parseable.
        test        — JSON output to stdout. Keeps test output clean
        and parseable by pytest log capture.
        production  — compact JSON output to stdout. Parsed by Filebeat
        and forwarded to Logstash → Elasticsearch.

        Log level:
            development — DEBUG (all events)
            test        — WARNING (suppress noise during test runs)
            production  — INFO (standard production verbosity)
            """

            # ── Determine environment-specific settings ───────────────────────────────
    use_json: bool = not settings.is_development

    log_level_str: str
    if settings.is_production:
        log_level_str = "INFO"
    elif settings.is_test:
        log_level_str = "WARNING"
    else:
        log_level_str = "DEBUG"

    log_level_int: int = getattr(logging, log_level_str)

    # ── Choose the final renderer ─────────────────────────────────────────────
    if use_json:
        # Production / test: compact JSON, one object per line.
        # orjson is used as the serialiser — it is faster than stdlib
        # json and handles datetime objects natively.
        renderer = structlog.processors.JSONRenderer(
            serializer=_orjson_serializer
        )
    else:
        # Development: coloured, aligned, human-readable console output.
        # renderer = structlog.dev.ConsoleRenderer(
        #     colors=True,
        #     exception_formatter=structlog.dev.plain_traceback,
        # )
        pass
    # ── Configure structlog ───────────────────────────────────────────────────
    structlog.configure(
        processors=[
            *_build_shared_processors(),
            # Final step: render the event dict to a string or bytes.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],

        # Use stdlib's BoundLogger as the wrapper class so that structlog
        # loggers support all stdlib methods (.info, .warning, .error, etc.)
        # and integrate cleanly with the stdlib logging config below.
        wrapper_class=structlog.stdlib.BoundLogger,

        # Store context in contextvars (asyncio-safe).
        # This is what allows request_id to be bound in middleware and
        # automatically appear in every log call made during that request,
        # even across await boundaries.
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),

        # cache_logger_on_first_use=True: after the first log call,
        # the bound logger is cached. Subsequent calls skip the
        # factory lookup. Safe and recommended for production.
        cache_logger_on_first_use=True,
    )

    # ── Configure stdlib logging ──────────────────────────────────────────────
    # This must run AFTER structlog.configure() because ProcessorFormatter
    # references structlog's configuration.
    logging.config.dictConfig(
        _build_stdlib_logging_config(log_level_str, use_json)
    )

    # ── Emit a startup confirmation ───────────────────────────────────────────
    # This is the first log line the application emits. Seeing it in the
    # expected format confirms the pipeline is wired correctly.
    log = structlog.get_logger(__name__)
    log.info(
        "logging_configured",
        renderer="json" if use_json else "console",
        level=log_level_str,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  orjson serialiser shim
# ══════════════════════════════════════════════════════════════════════════════

def _orjson_serializer(obj: Any, **kwargs: Any) -> str:
    """
    Use orjson to serialise the structlog event dict to a JSON string.

    orjson handles:
        - datetime objects (rendered as ISO 8601 strings automatically)
        - UUID objects (rendered as lowercase hyphenated strings)
        - bytes objects (rendered as base64)
        - numpy arrays (if numpy is installed)

        orjson.dumps() returns bytes — we decode to str because structlog
        expects the final renderer to return a str that stdlib logging
        can write to the stream handler.

        The `**kwargs` absorbs any extra arguments structlog may pass
        (e.g. `indent` when pretty-printing) — orjson ignores unknown kwargs
        so we accept and discard them to stay compatible with structlog's
        renderer contract.
        """
    import orjson
    return orjson.dumps(obj).decode("utf-8")