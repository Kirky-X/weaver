# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Proxy-aware client IP resolution.

Default posture is zero-trust: ``X-Forwarded-For`` is honored only when the
direct peer address appears in ``api.trusted_proxies``. Behind a reverse
proxy, configure the proxy address there (and run uvicorn with
``--proxy-headers`` / ``forwarded-allow-ips``) so per-IP rate limiting,
blocking and audit attribution keep working.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.observability import get_logger

log = get_logger(__name__)


def _trusted_proxies() -> list[str]:
    """Read ``api.trusted_proxies`` from global settings; degrade to zero-trust."""
    try:
        from container.access import get_settings

        return list(get_settings().api.trusted_proxies)
    except (RuntimeError, ImportError) as exc:
        log.debug("trusted_proxies_unavailable", error=str(exc))
        return []


def resolve_client_ip(
    client_host: str | None,
    forwarded_for: str | None,
    trusted_proxies: Sequence[str],
) -> str:
    """Resolve the originating client IP.

    The right-most ``X-Forwarded-For`` hop is the value appended by the
    closest trusted proxy, so it is used only when the direct peer itself
    is trusted; otherwise the header is treated as attacker-controlled.
    """
    if not client_host:
        return "unknown"
    if forwarded_for and client_host in trusted_proxies:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return client_host


def get_client_ip(request: object, trusted_proxies: Sequence[str] | None = None) -> str:
    """Resolve client IP from a Starlette ``Request``."""
    proxies = trusted_proxies if trusted_proxies is not None else _trusted_proxies()
    client = getattr(request, "client", None)
    client_host = client.host if client else None
    forwarded_for = request.headers.get("x-forwarded-for")  # type: ignore[attr-defined]
    return resolve_client_ip(client_host, forwarded_for, proxies)


def get_client_ip_from_scope(
    scope: dict, trusted_proxies: Sequence[str] | None = None
) -> str:
    """Resolve client IP from a raw ASGI scope."""
    proxies = trusted_proxies if trusted_proxies is not None else _trusted_proxies()
    client = scope.get("client")
    client_host = client[0] if client else None
    forwarded_for = None
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            forwarded_for = value.decode("utf-8", errors="replace")
            break
    return resolve_client_ip(client_host, forwarded_for, proxies)
