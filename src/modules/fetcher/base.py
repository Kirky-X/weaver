"""Base fetcher interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseFetcher(ABC):
    """Abstract interface for all fetcher implementations."""

    @abstractmethod
    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content from a URL.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (HTTP status code, content, response headers).

        Raises:
            Exception: On network or parsing errors.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...
