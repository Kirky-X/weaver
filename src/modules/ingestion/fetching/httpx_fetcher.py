# Copyright (c) 2026 KirkyX. All Rights Reserved
"""httpx-based fetcher for standard HTTP requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from core.resilience.retry import retry_network
from modules.ingestion.fetching.base import BaseFetcher

if TYPE_CHECKING:
    from core.security import URLValidator

log = get_logger("httpx_fetcher")


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
        user_agent: User-Agent header value.
        http2: Enable HTTP/2 multiplexing (default True).
        max_connections: Maximum connections in pool.
        max_keepalive: Maximum keepalive connections.
        url_validator: Optional URL validator for SSRF protection.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (compatible; NewsBot/1.0)",
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

        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            max_redirects=10,  # Limit redirects to prevent loops
            http2=http2,
            limits=limits,
        )
        self._http2_enabled = http2
        self._url_validator = url_validator

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via httpx with automatic retry on transient errors.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (status_code, response_text, response_headers).

        Raises:
            URLValidationError: If URL is blocked for SSRF protection.
            RedirectBlockedError: If a redirect is blocked for security.
        """
        import time

        start = time.monotonic()

        # Security validation - do NOT retry if this fails
        if self._url_validator:
            await self._url_validator.validate(url)

        # Network operation with retry
        async for attempt in retry_network(max_attempts=3, min_wait=1.0, max_wait=10.0):
            with attempt:
                try:
                    # Build request to allow redirect inspection
                    request = self._client.build_request("GET", url, headers=headers or {})

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
            URLValidationError: If URL is blocked for SSRF protection.
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
                headers=headers or {},
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
