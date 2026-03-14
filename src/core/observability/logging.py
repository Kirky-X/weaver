"""loguru configuration for structured JSON logging."""

from __future__ import annotations

import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger


_context_vars: ContextVar[dict[str, Any]] = ContextVar("context_vars", default={})


def configure_logging(debug: bool = False) -> None:
    """Configure loguru with JSON rendering and context vars.

    Args:
        debug: If True, use a lower log level for development.
    """
    level = "DEBUG" if debug else "INFO"

    logger.remove()

    logger.add(
        sys.stderr,
        format="{extra}",
        level=level,
        serialize=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a loguru logger with context binding.

    Args:
        name: Optional logger name for context.

    Returns:
        A bound loguru logger instance.
    """
    bound_logger = logger.bind(**_context_vars.get())
    if name:
        bound_logger = bound_logger.bind(component=name)
    return bound_logger
