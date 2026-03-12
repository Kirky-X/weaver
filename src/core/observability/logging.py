"""structlog configuration for structured JSON logging."""

from __future__ import annotations

import structlog


def configure_logging(debug: bool = False) -> None:
    """Configure structlog with JSON rendering and context vars.

    Args:
        debug: If True, use a lower log level for development.
    """
    min_level = 10 if debug else 20  # DEBUG=10, INFO=20

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog bound logger.

    Args:
        name: Optional logger name for context.

    Returns:
        A bound structlog logger instance.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(component=name)
    return logger
