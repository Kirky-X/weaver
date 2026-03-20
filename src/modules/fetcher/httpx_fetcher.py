# Copyright (c) 2026 KirkyX. All Rights Reserved
"""httpx-based fetcher for standard HTTP requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from modules.fetcher.base import BaseFetcher

if TYPE_CHECKING:
    pass

log = get_logger("httpx_fetcher")


class HttpxFetcher(BaseFetcher):
    """Lightweight fetcher using httpx for simple HTTP requests.

    Args:
        timeout: Request timeout in seconds.
        user_agent: User-Agent header value.
        http2: Enable HTTP/2 multiplexing (default True).
        max_connections: Maximum connections in pool.
        max_keepalive: Maximum keepalive connections.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)",
        http2: bool = True,
        max_connections: int = 100,
        max_keepalive: int = 20,
    ) -> None:
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
            keepalive_expiry=30.0,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            http2=http2,
            limits=limits,
        )
        self._http2_enabled = http2

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via httpx.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (status_code, response_text, response_headers).
        """
        import time

        start = time.monotonic()
        try:
            response = await self._client.get(url, headers=headers or {})
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="success").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.debug(
                "httpx_fetch_ok",
                url=url,
                status=response.status_code,
                http_version=response.http_version,
            )
            return response.status_code, response.text, dict(response.headers)
        except httpx.HTTPStatusError as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_status_error", url=url, status=exc.response.status_code)
            raise
        except httpx.HTTP2Error as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="http2_error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_http2_error", url=url, error=str(exc))
            raise
        except Exception as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_fetch_error", url=url, error=str(exc))
            raise

    async def close(self) -> None:
        """Close the httpx client."""
        await self._client.aclose()

    @property
    def http2_enabled(self) -> bool:
        """Check if HTTP/2 is enabled."""
        return self._http2_enabled
