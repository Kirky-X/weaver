# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""httpx-based fetcher for standard HTTP requests."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any

import httpx

from core.constants import NEWSBOT_USER_AGENT
from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from core.resilience.retry import retry_network
from core.security.validation.ssrf import SSRFError
from modules.ingestion.fetching.base import BaseFetcher

if TYPE_CHECKING:
    from core.security import URLValidator

log = get_logger(__name__)

# Default UA when caller does not supply ``user_agents``. Kept as a
# module-level constant so tests and docs can reference the same value.
_DEFAULT_USER_AGENTS: list[str] = [NEWSBOT_USER_AGENT]


class RedirectBlockedError(Exception):
    """Raised when a redirect is blocked for security reasons."""

    def __init__(self, redirect_url: str, reason: str):
        self.redirect_url = redirect_url
        self.reason = reason
        super().__init__(f"Redirect to '{redirect_url}' blocked: {reason}")


class SecureRedirectHandler:
    """httpx response event-hook validating each redirect target *before*
    the next hop is requested (pre-request SSRF guard).

    Registered via ``AsyncClient(event_hooks={"response": [...]})``: httpx
    fires the hook after every hop's response arrives and only then builds
    and sends the next redirect request, so raising here prevents any
    request from ever reaching the unvalidated target.
    """

    _REDIRECT_STATUS = {301, 302, 303, 307, 308}

    def __init__(self, validator: URLValidator | None = None) -> None:
        """Initialize with optional URL validator.

        Args:
            validator: URL validator instance for SSRF protection.
        """
        self._validator = validator

    async def __call__(self, response: httpx.Response) -> None:
        """Validate the connection IP and any redirect target.

        Two checks per hop:
        1. The IP the connection actually reached (from the network stream's
           ``server_addr``) — authoritative against DNS rebinding, since
           resolution-time validation races the connect.
        2. A 3xx ``Location`` target, before httpx requests the next hop.

        Args:
            response: The just-received response.

        Raises:
            RedirectBlockedError: If the connected IP or redirect target is
                blocked.
        """
        if not self._validator:
            return

        # 1) Connected-IP check (anti-rebinding) — applies to every response.
        server_addr = self._connected_ip(response)
        if server_addr:
            url = str(response.request.url)
            try:
                self._validator.check_connected_ip(server_addr, url)
                log.debug(
                    "connected_ip_validated",
                    server_addr=server_addr,
                    url=url,
                )
            except RedirectBlockedError:
                raise
            except Exception as exc:
                log.warning(
                    "connected_ip_blocked",
                    server_addr=server_addr,
                    url=url,
                    reason=str(exc),
                )
                raise RedirectBlockedError(url, str(exc)) from exc

        # 2) Redirect-target check.
        if response.status_code not in self._REDIRECT_STATUS:
            return

        location = response.headers.get("location")
        if not location:
            return

        redirect_url = str(response.url.join(location))

        try:
            # Synchronous checks first (cheap, no DNS)
            if not self._validator.is_safe_url(redirect_url):
                raise RedirectBlockedError(redirect_url, "URL failed synchronous security check")

            # Full async validation (DNS resolution, private-network checks)
            await self._validator.validate(redirect_url)
            log.debug("redirect_validated", redirect_url=redirect_url)

        except RedirectBlockedError:
            raise
        except Exception as exc:
            log.warning(
                "redirect_blocked",
                redirect_url=redirect_url,
                reason=str(exc),
            )
            raise RedirectBlockedError(redirect_url, str(exc)) from exc

    @staticmethod
    def _connected_ip(response: httpx.Response) -> str | None:
        """Extract the remote IP the connection actually reached, if exposed.

        httpcore exposes it via ``response.extensions["network_stream"]``.
        Returns None when unavailable (mock transports, proxies returning
        non-tuple addresses, etc.).
        """
        stream = response.extensions.get("network_stream")
        if stream is None:
            return None
        try:
            info = stream.get_extra_info("server_addr")
        except Exception:
            return None
        if isinstance(info, tuple) and info:
            return str(info[0])
        if isinstance(info, str):
            return info
        return None


class HttpxFetcher(BaseFetcher):
    """Lightweight fetcher using httpx for simple HTTP requests.

    Args:
        timeout: Request timeout in seconds.
        user_agents: User-Agent pool — each request draws a random UA
            from this list (fix). Defaults to a single-UA pool to
            preserve backward-compatible behavior.
        http2: Enable HTTP/2 multiplexing (default True).
        max_connections: Maximum connections in pool.
        max_keepalive: Maximum keepalive connections.
        url_validator: Optional URL validator for SSRF protection.
        transport: Optional custom httpx transport (tests inject
            ``httpx.MockTransport``; production leaves it None).
    """

    def __init__(
        self,
        timeout: float = 15.0,
        user_agents: list[str] | None = None,
        http2: bool = True,
        max_connections: int = 100,
        max_keepalive: int = 20,
        url_validator: URLValidator | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
            keepalive_expiry=30.0,
        )

        # Register the redirect guard as a response event-hook: httpx fires
        # it after each hop's response and before requesting the next hop,
        # so an unvalidated redirect target is never contacted.
        self._redirect_handler = SecureRedirectHandler(url_validator)

        # Per-request UA rotation: do NOT set a client-level
        # User-Agent header; instead, _get_headers picks one randomly
        # from self._user_agents on every request. Caller-supplied
        # headers still win (see _get_headers).
        self._user_agents = list(user_agents) if user_agents else list(_DEFAULT_USER_AGENTS)

        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": True,
            "max_redirects": 10,  # Limit redirects to prevent loops
            "http2": http2,
            "limits": limits,
            "event_hooks": ({"response": [self._redirect_handler]} if url_validator else None),
            # 抓取器必须直连目标：trust_env 默认拾取环境变量与 Windows
            # 注册表系统代理（urllib.getproxies），请求会经本机代理
            # （如 127.0.0.1:10808）出站，SSRF connected-IP 反绑定检查
            # 随即把代理地址误判为内网目标而拦截。代理出站需求应显式
            # 注入 transport，而非隐式继承桌面代理。
            "trust_env": False,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**client_kwargs)
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
                SSRF/URLhaus/PhishTank checks.

        Returns:
            Tuple of (status_code, response_text, response_headers).

        Raises:
            SSRFError: If URL is blocked for SSRF protection.
            RedirectBlockedError: If a redirect is blocked for security.
        """
        start = time.monotonic()

        # Security validation - do NOT retry if this fails.
        # Skip when caller (e.g. SmartFetcher) has already validated upstream
        # to avoid duplicate SSRF + URLhaus + PhishTank network round-trips.
        if self._url_validator and not pre_validated:
            result = await self._url_validator.validate(url)
            if not result.is_safe:
                raise SSRFError(
                    url=url,
                    message=f"URL blocked by security validation: {result.risk.value}",
                )

        # Network operation with retry
        async for attempt in retry_network(max_attempts=3, min_wait=1.0, max_wait=10.0):
            with attempt:
                try:
                    # Build request to allow redirect inspection.
                    # Per-request UA rotation via _get_headers (fix):
                    # caller headers override pool-selected UA.
                    request = self._client.build_request(
                        "GET", url, headers=self._get_headers(headers)
                    )

                    # Redirect targets are validated by the client-level
                    # event-hook (SecureRedirectHandler) before each hop.
                    response = await self._client.send(request, follow_redirects=True)

                    # send() does NOT raise for HTTP error statuses — surface
                    # them as HTTPStatusError so the 429/503 Retry-After
                    # backoff and 5xx retry logic below are reachable.
                    if response.status_code >= 400:
                        response.raise_for_status()

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
                    # signal before re-raising (fix). Cap the wait at
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

        # Unreachable: retry_network(reraise=True) re-raises the last exception
        # when the retry budget is exhausted, so this loop never exits normally.
        raise AssertionError("unreachable: retry_network always raises on exhaustion")

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
        start = time.monotonic()
        try:
            # Validate URL before making request (SSRF protection)
            if self._url_validator:
                result = await self._url_validator.validate(url)
                if not result.is_safe:
                    raise SSRFError(
                        url=url,
                        message=f"URL blocked by security validation: {result.risk.value}",
                    )

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

    async def close(self) -> None:
        """Close the httpx client."""
        await self._client.aclose()

    @property
    def http2_enabled(self) -> bool:
        """Check if HTTP/2 is enabled."""
        return self._http2_enabled
