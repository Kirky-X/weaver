# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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

    async def fetch_bytes(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes, dict[str, str]]:
        """Fetch a URL and return the body as raw bytes.

        ``fetch`` decodes the body to ``str``, which silently corrupts binary
        payloads (e.g. PDFs) because no reliable encoding can be inferred for
        non-text media types. Callers that need byte-exact content use this
        method instead.

        Not abstract: fetchers that cannot preserve raw bytes fall back to
        encoding the decoded text as UTF-8, which is the best available
        approximation and keeps the contract total for every implementation.
        Implementations that can do better (``HttpxFetcher``) override it.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (HTTP status code, content bytes, response headers).

        Raises:
            Exception: On network or parsing errors.
        """
        status, text, resp_headers = await self.fetch(url, headers)
        return status, text.encode("utf-8", errors="replace"), resp_headers

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...
