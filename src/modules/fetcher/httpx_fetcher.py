"""httpx-based fetcher for standard HTTP requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from modules.fetcher.base import BaseFetcher
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector

if TYPE_CHECKING:
    from modules.fetcher.rate_limiter import HostRateLimiter

log = get_logger("httpx_fetcher")


class HttpxFetcher(BaseFetcher):
    """Lightweight fetcher using httpx for simple HTTP GET requests.

    Args:
        timeout: Request timeout in seconds.
        user_agent: User-Agent header value.
        rate_limiter: Optional rate limiter for per-host delays.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)",
        rate_limiter: HostRateLimiter | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            http2=False,
        )
        self._rate_limiter = rate_limiter

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

        if self._rate_limiter:
            await self._rate_limiter.acquire(url)

        start = time.monotonic()
        try:
            response = await self._client.get(url, headers=headers or {})
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="success").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.debug("httpx_fetch_ok", url=url, status=response.status_code)
            return response.status_code, response.text, dict(response.headers)
        except Exception as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_fetch_error", url=url, error=str(exc))
            raise

    async def close(self) -> None:
        """Close the httpx client."""
        await self._client.aclose()
