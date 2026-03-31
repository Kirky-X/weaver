# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Fetcher-specific exception classes for type-safe error handling."""

from __future__ import annotations


class FetchError(Exception):
    """Unified fetch error with complete context.

    Wraps all fetch-related failures with URL, message, and original exception.

    Attributes:
        url: The URL that was being fetched when the error occurred.
        message: Human-readable error description.
        cause: The original exception that caused this error, if any.
    """

    def __init__(
        self,
        url: str,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        self.url = url
        self.message = message
        self.cause = cause
        super().__init__(f"{url}: {message}")

    def __repr__(self) -> str:
        return f"FetchError(url={self.url!r}, message={self.message!r}, cause={self.cause!r})"


class CircuitOpenError(FetchError):
    """Raised when a circuit breaker is open and blocking requests.

    Indicates that the target host has been blocked due to consecutive failures.

    Attributes:
        host: The host name for which the circuit breaker is open.
    """

    def __init__(self, host: str) -> None:
        self.host = host
        super().__init__(
            url="",
            message=f"Circuit breaker open for host: {host}",
        )

    def __repr__(self) -> str:
        return f"CircuitOpenError(host={self.host!r})"
