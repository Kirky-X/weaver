# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""httpx-based fetcher for standard HTTP requests."""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Any

import httpx

from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from core.resilience.retry import retry_network
from modules.ingestion.fetching.base import BaseFetcher

if TYPE_CHECKING:
    from core.security import URLValidator

log = get_logger(__name__)

# Default UA when caller does not supply ``user_agents``. Kept as a
# module-level constant so tests and docs can reference the same value.
_DEFAULT_USER_AGENTS: list[str] = ["Mozilla/5.0 (compatible; NewsBot/1.0)"]


class RedirectBlockedError(Exception):
    """Raised when a redirect is blocked for security reasons."""

    def __init__(self, redirect_url: str, reason: str):
        self.redirect_url = redirect_url
        self.reason = reason
        super().__init__(f"Redirect to '{redirect_url}' blocked: {reason}")


class SecureRedirectHandler:
    """Custom redirect handler that validates redirect URLs for SSRF protection."""

    def __init__(self, validator: URLValidator | None = None) -> None:
        """Initialize with optional URL validator.

        Args:
            validator: URL validator instance for SSRF protection.
        """
        self._validator = validator

    async def validate_redirect(self, request: httpx.Request, response: httpx.Response) -> None:
        """Validate redirect URL before following.

        This is called before each redirect is followed.

        Args:
            request: The redirect request.
            response: The response that triggered the redirect.

        Raises:
            RedirectBlockedError: If redirect URL is blocked.
        """
        if not self._validator:
            return

        redirect_url = str(request.url)

        try:
            # Use synchronous check first (faster)
            if not self._validator.is_safe_url(redirect_url):
                raise RedirectBlockedError(redirect_url, "URL failed synchronous security check")

            # Full async validation
            await self._validator.validate(redirect_url)
            log.debug("redirect_validated", redirect_url=redirect_url)

        except Exception as exc:
            log.warning(
                "redirect_blocked",
                redirect_url=redirect_url,
                reason=str(exc),
            )
            raise RedirectBlockedError(redirect_url, str(exc)) from exc


class HttpxFetcher(BaseFetcher):
    """Lightweight fetcher using httpx for simple HTTP requests.

    Args:
        timeout: Request timeout in seconds.
        user_agents: User-Agent pool — each request draws a random UA
            from this list (P1-4 fix). Defaults to a single-UA pool to
            preserve backward-compatible behavior.
        http2: Enable HTTP/2 multiplexing (default True).
        max_connections: Maximum connections in pool.
        max_keepalive: Maximum keepalive connections.
        url_validator: Optional URL validator for SSRF protection.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agents: list[str] | None = None,
        http2: bool = True,
        max_connections: int = 100,
        max_keepalive: int = 20,
        url_validator: URLValidator | None = None,
    ) -> None:
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
            keepalive_expiry=30.0,
        )

        # Configure redirect handling
        # httpx supports max_redirects, default is 20
        self._redirect_handler = SecureRedirectHandler(url_validator)

        # Per-request UA rotation (P1-4): do NOT set a client-level
        # User-Agent header; instead, _get_headers picks one randomly
        # from self._user_agents on every request. Caller-supplied
        # headers still win (see _get_headers).
        self._user_agents = list(user_agents) if user_agents else list(_DEFAULT_USER_AGENTS)

        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=10,  # Limit redirects to prevent loops
            http2=http2,
            limits=limits,
        )
        self._http2_enabled = http2
        self._url_validator = url_validator

    def _get_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        """Build request headers with per-request UA rotation.

        Caller-supplied ``User-Agent`` wins over pool selection, so
        per-request overrides (e.g. site-specific UA) still work.

        Args:
            headers: Caller-supplied headers (may be None).

        Returns:
            Merged headers dict with a User-Agent selected from the pool.
        """
        # UA 轮换非密码学用途
        merged: dict[str, str] = {"User-Agent": random.choice(self._user_agents)}  # nosec B311
        if headers:
            merged.update(headers)
        return merged

    async def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        pre_validated: bool = False,
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via httpx with automatic retry on transient errors.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.
            pre_validated: If True, skip url_validator.validate (caller has
                already validated). Used by SmartFetcher to avoid double
                SSRF/URLhaus/PhishTank checks. See ``temp/report.md`` D3.

        Returns:
            Tuple of (status_code, response_text, response_headers).

        Raises:
            SSRFError: If URL is blocked for SSRF protection.
            RedirectBlockedError: If a redirect is blocked for security.
        """
        import time

        start = time.monotonic()

        # Security validation - do NOT retry if this fails.
        # Skip when caller (e.g. SmartFetcher) has already validated upstream
        # to avoid duplicate SSRF + URLhaus + PhishTank network round-trips.
        if self._url_validator and not pre_validated:
            await self._url_validator.validate(url)

        # Network operation with retry
        async for attempt in retry_network(max_attempts=3, min_wait=1.0, max_wait=10.0):
            with attempt:
                try:
                    # Build request to allow redirect inspection.
                    # Per-request UA rotation via _get_headers (P1-4 fix):
                    # caller headers override pool-selected UA.
                    request = self._client.build_request(
                        "GET", url, headers=self._get_headers(headers)
                    )

                    # Send with streaming to intercept redirects
                    response = await self._client.send(request, follow_redirects=True)

                    # Check redirect chain for security - do NOT retry if this fails
                    if response.history and self._url_validator:
                        await self._validate_redirect_chain(response.history, url)

                    latency = time.monotonic() - start
                    MetricsCollector.fetch_total.labels(method="httpx", status="success").inc()
                    MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
                    log.debug(
                        "httpx_fetch_ok",
                        url=url,
                        status=response.status_code,
                        http_version=response.http_version,
                        redirects=len(response.history),
                    )
                    return response.status_code, response.text, dict(response.headers)

                except RedirectBlockedError:
                    # Security errors - do not retry, propagate immediately
                    latency = time.monotonic() - start
                    MetricsCollector.fetch_total.labels(method="httpx", status="blocked").inc()
                    MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
                    raise

                except httpx.HTTPStatusError as exc:
                    # HTTP errors (4xx, 5xx) - let retry logic handle server errors
                    latency = time.monotonic() - start

                    # 429/503 + Retry-After: respect the server's backoff
                    # signal before re-raising (P1-4 fix). Cap the wait at
                    # 60s so a hostile server cannot stall the crawler
                    # indefinitely. Re-raise so retry_network still owns
                    # the retry-loop accounting.
                    if exc.response.status_code in (429, 503):
                        retry_after = exc.response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                wait = min(float(retry_after), 60.0)
                            except (TypeError, ValueError):
                                wait = 0.0
                            if wait > 0:
                                log.warning(
                                    "httpx_429_503_retry_after",
                                    url=url,
                                    status=exc.response.status_code,
                                    wait=wait,
                                )
                                await asyncio.sleep(wait)
                            raise

                    if exc.response.status_code >= 500:
                        # Server errors are transient, retry
                        log.warning(
                            "httpx_server_error_retryable",
                            url=url,
                            status=exc.response.status_code,
                        )
                        raise  # Let retry_network handle
                    # Client errors (4xx) are not retryable
                    MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
                    MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
                    raise

                except httpx.TransportError as exc:
                    # Transport errors are transient, retry
                    latency = time.monotonic() - start
                    MetricsCollector.fetch_total.labels(
                        method="httpx", status="transport_error"
                    ).inc()
                    MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
                    log.warning(
                        "httpx_transport_error_retryable",
                        url=url,
                        error=str(exc),
                    )
                    raise  # Let retry_network handle

        raise RuntimeError("Fetch retry exhausted")  # Should never reach here

    async def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str, dict[str, str]]:
        """Send POST request via httpx.

        Args:
            url: The URL to post to.
            data: Form data to send in request body.
            json_data: JSON data to send in request body.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (status_code, response_text, response_headers).

        Raises:
            SSRFError: If URL is blocked for SSRF protection.
            httpx.HTTPStatusError: On HTTP error status.
            httpx.TransportError: On transport error.
        """
        import time

        start = time.monotonic()
        try:
            # Validate URL before making request (SSRF protection)
            if self._url_validator:
                await self._url_validator.validate(url)

            response = await self._client.post(
                url,
                data=data,
                json=json_data,
                headers=self._get_headers(headers),
            )

            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="success").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.debug(
                "httpx_post_ok",
                url=url,
                status=response.status_code,
            )
            return response.status_code, response.text, dict(response.headers)

        except httpx.HTTPStatusError as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_status_error", url=url, status=exc.response.status_code)
            raise
        except httpx.TransportError as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="transport_error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_transport_error", url=url, error=str(exc))
            raise
        except Exception as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="httpx", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="httpx").observe(latency)
            log.warning("httpx_post_error", url=url, error=str(exc))
            raise

    async def _validate_redirect_chain(
        self, history: list[httpx.Response], original_url: str
    ) -> None:
        """Validate all URLs in redirect chain.

        Args:
            history: List of redirect responses.
            original_url: The original URL requested.

        Raises:
            RedirectBlockedError: If any redirect URL is blocked.
        """
        if not self._url_validator:
            return

        for i, response in enumerate(history):
            redirect_url = str(response.url)

            # Skip the first URL (original) as it was already validated
            if i == 0 and redirect_url == original_url:
                continue

            try:
                # Quick synchronous check first
                if not self._url_validator.is_safe_url(redirect_url):
                    raise RedirectBlockedError(
                        redirect_url, "Failed security check in redirect chain"
                    )

                log.debug("redirect_chain_validated", redirect_url=redirect_url, step=i)

            except RedirectBlockedError:
                raise
            except Exception as exc:
                log.warning(
                    "redirect_chain_blocked",
                    redirect_url=redirect_url,
                    step=i,
                    reason=str(exc),
                )
                raise RedirectBlockedError(redirect_url, str(exc)) from exc

    async def close(self) -> None:
        """Close the httpx client."""
        await self._client.aclose()

    @property
    def http2_enabled(self) -> bool:
        """Check if HTTP/2 is enabled."""
        return self._http2_enabled
