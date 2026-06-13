from __future__ import annotations

import logging
import structlog
from typing import Optional

log = structlog.get_logger(__name__)

# Canonical level name → stdlib int mapping
_LEVEL_MAP: dict[str, int] = {
    "debug":    logging.DEBUG,
    "info":     logging.INFO,
    "warning":  logging.WARNING,
    "error":    logging.ERROR,
    "critical": logging.CRITICAL,
}


def set_log_level(logger_name: str, level: str) -> None:
    """
    Dynamically set the log level for a named stdlib logger at runtime.

    Used by ops scripts or a future /admin/log-level endpoint to
    temporarily increase verbosity on a specific subsystem without
    restarting the process.

    Args:
        logger_name: The stdlib logger name, e.g. "sqlalchemy.engine",
        "services.chat_service", or "" for the root logger.
        level:       Case-insensitive level name: debug | info | warning |
        error | critical.

        Example:
            set_log_level("sqlalchemy.engine", "debug")
            # Now all SQL statements are logged until you call:
                set_log_level("sqlalchemy.engine", "warning")
                """
    level_lower = level.lower().strip()
    level_int = _LEVEL_MAP.get(level_lower)

    if level_int is None:
        raise ValueError(
    f"Unknown log level '{level}'. "
    f"Valid values: {', '.join(_LEVEL_MAP.keys())}"
    )

    target_logger = logging.getLogger(logger_name or None)  # type: ignore[arg-type]
    target_logger.setLevel(level_int)

    log.info(
        "log_level_changed",
        logger=logger_name or "root",
        new_level=level_lower,
    )


def get_log_level(logger_name: str) -> str:
    """
    Return the effective log level name for a named logger.

    "Effective" means the level that actually applies after
    propagation is considered — if logger_name has no explicit level,
    it inherits from its parent.

    Args:
        logger_name: Logger name or "" for the root logger.

        Returns:
            Level name string: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
            """
    target_logger = logging.getLogger(logger_name or None)  # type: ignore[arg-type]
    level_int = target_logger.getEffectiveLevel()
    return logging.getLevelName(level_int)


def get_all_logger_levels() -> dict[str, str]:
    """
    Return a snapshot of every named logger and its current effective level.

    Useful for a diagnostics endpoint — call this from an /admin/loggers
    route (protected behind admin auth) to see the current state of all
    loggers at runtime.

    Returns:
        Dict mapping logger name → effective level name.
        Sorted alphabetically by logger name.
        """
    manager = logging.Logger.manager
    result: dict[str, str] = {
        "root": logging.getLevelName(logging.getLogger().getEffectiveLevel())
    }

    for name in sorted(manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        result[name] = logging.getLevelName(logger.getEffectiveLevel())

        return result