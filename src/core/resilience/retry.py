# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified retry strategies using tenacity.

Provides standardized retry decorators for network, LLM, and database operations
with exponential backoff, jitter, and unified logging.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from core.llm.output_validator import OutputParserException
from core.observability.logging import get_logger

log = get_logger("retry")

T = TypeVar("T")

# Default retry configurations
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_WAIT = 1.0  # seconds
DEFAULT_MAX_WAIT = 30.0  # seconds
DEFAULT_JITTER = 1.0  # seconds

# Exception types for network operations
NETWORK_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Exception types for LLM operations
LLM_EXCEPTIONS: tuple[type[Exception], ...] = (
    TimeoutError,
    ConnectionError,
)

# Exception types for database operations
DB_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log retry attempts with structured logging.

    Args:
        retry_state: The retry state from tenacity.
    """
    if retry_state.outcome is None:
        return
    exception = retry_state.outcome.exception()
    if exception is None:
        return
    log.warning(
        "retry_attempt",
        attempt=retry_state.attempt_number,
        delay=retry_state.idle_for,
        exception_type=type(exception).__name__,
        exception_message=str(exception),
    )


def _create_retry_strategy(
    exception_types: tuple[type[Exception], ...],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
    jitter: float = DEFAULT_JITTER,
    max_delay: float | None = None,
) -> AsyncRetrying:
    """Create a retry strategy for specific exception types.

    Args:
        exception_types: Tuple of exception types to retry on.
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        jitter: Maximum random jitter to add (seconds).
        max_delay: Maximum total retry time (seconds), None for no limit.

    Returns:
        AsyncRetrying instance configured for the specified exceptions.
    """
    stop: Any = stop_after_attempt(max_attempts)
    if max_delay is not None:
        stop = stop | stop_after_delay(max_delay)

    return AsyncRetrying(
        reraise=True,
        stop=stop,
        wait=wait_exponential_jitter(
            initial=min_wait,
            max=max_wait,
            jitter=jitter,
        ),
        retry=retry_if_exception_type(exception_types),
        before_sleep=_log_retry_attempt,
    )


def retry_network(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
    jitter: float = DEFAULT_JITTER,
    max_delay: float | None = None,
) -> AsyncRetrying:
    """Create a retry strategy for network operations.

    Suitable for HTTP requests, web scraping, and other network-bound operations.
    Retries on connection errors, timeouts, and OS errors.

    Args:
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        jitter: Maximum random jitter to add (seconds).
        max_delay: Maximum total retry time (seconds), None for no limit.

    Returns:
        AsyncRetrying instance configured for network operations.
    """
    return _create_retry_strategy(
        NETWORK_EXCEPTIONS,
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
        jitter=jitter,
        max_delay=max_delay,
    )


def retry_llm(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
    jitter: float = DEFAULT_JITTER,
    max_delay: float | None = None,
) -> AsyncRetrying:
    """Create a retry strategy for LLM operations.

    Suitable for LLM API calls. Retries on timeouts, connection errors,
    and output parsing exceptions.

    Args:
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        jitter: Maximum random jitter to add (seconds).
        max_delay: Maximum total retry time (seconds), None for no limit.

    Returns:
        AsyncRetrying instance configured for LLM operations.
    """
    return _create_retry_strategy(
        LLM_EXCEPTIONS + (OutputParserException,),
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
        jitter=jitter,
        max_delay=max_delay,
    )


def retry_db(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
    jitter: float = DEFAULT_JITTER,
    max_delay: float | None = None,
) -> AsyncRetrying:
    """Create a retry strategy for database operations.

    Suitable for database queries and transactions. Retries on connection
    errors, timeouts, and OS errors.

    Args:
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        jitter: Maximum random jitter to add (seconds).
        max_delay: Maximum total retry time (seconds), None for no limit.

    Returns:
        AsyncRetrying instance configured for database operations.
    """
    return _create_retry_strategy(
        DB_EXCEPTIONS,
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
        jitter=jitter,
        max_delay=max_delay,
    )


def _create_retry_decorator(
    retry_func: Callable[..., AsyncRetrying],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Create a retry decorator for async functions.

    Args:
        retry_func: The retry strategy function to use.
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).

    Returns:
        A decorator function.
    """
    retryer = retry_func(
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
    )

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async for attempt in retryer:
                with attempt:
                    return await fn(*args, **kwargs)  # type: ignore[misc]
            raise RuntimeError("Retry exhausted")

        return wrapper  # type: ignore[return-value]

    return decorator


def with_network_retry(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for async functions that need network retry logic.

    Usage:
        @with_network_retry(max_attempts=3)
        async def fetch_url(url: str) -> str:
            ...
    """
    return _create_retry_decorator(retry_network, max_attempts, min_wait, max_wait)


def with_llm_retry(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for async functions that need LLM retry logic.

    Usage:
        @with_llm_retry(max_attempts=3)
        async def call_llm(prompt: str) -> str:
            ...
    """
    return _create_retry_decorator(retry_llm, max_attempts, min_wait, max_wait)


def with_db_retry(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for async functions that need database retry logic.

    Usage:
        @with_db_retry(max_attempts=3)
        async def query_database(query: str) -> list:
            ...
    """
    return _create_retry_decorator(retry_db, max_attempts, min_wait, max_wait)
