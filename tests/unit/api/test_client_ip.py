# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for proxy-aware client IP resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.utils.client_ip import (
    get_client_ip,
    get_client_ip_from_scope,
    resolve_client_ip,
)


class TestResolveClientIp:
    """Core resolution logic."""

    def test_direct_connection_returns_peer(self) -> None:
        assert resolve_client_ip("10.0.0.5", None, []) == "10.0.0.5"

    def test_missing_client_returns_unknown(self) -> None:
        assert resolve_client_ip(None, "1.2.3.4", ["10.0.0.1"]) == "unknown"

    def test_spoofed_xff_ignored_for_untrusted_peer(self) -> None:
        """XFF from a non-trusted peer must be ignored (anti-spoofing)."""
        assert resolve_client_ip("10.0.0.5", "1.2.3.4", []) == "10.0.0.5"

    def test_trusted_proxy_returns_last_xff_hop(self) -> None:
        assert resolve_client_ip("10.0.0.1", "1.2.3.4", ["10.0.0.1"]) == "1.2.3.4"

    def test_trusted_proxy_multi_hop_returns_rightmost(self) -> None:
        xff = "203.0.113.9, 10.0.0.2, 10.0.0.1"
        assert resolve_client_ip("10.0.0.1", xff, ["10.0.0.1"]) == "10.0.0.1"

    def test_trusted_proxy_empty_xff_returns_peer(self) -> None:
        assert resolve_client_ip("10.0.0.1", "", ["10.0.0.1"]) == "10.0.0.1"


class TestGetClientIpFromRequest:
    """Starlette Request adapter."""

    def _request(self, host: str | None, headers: dict[str, str] | None = None):
        request = MagicMock()
        request.client = MagicMock(host=host) if host is not None else None
        request.headers.get = lambda key, default=None: (headers or {}).get(key, default)
        return request

    def test_untrusted_peer_ignores_forwarded_header(self) -> None:
        request = self._request("192.168.1.10", {"x-forwarded-for": "6.6.6.6"})
        assert get_client_ip(request, trusted_proxies=[]) == "192.168.1.10"

    def test_trusted_peer_uses_forwarded_header(self) -> None:
        request = self._request("172.17.0.1", {"x-forwarded-for": "8.8.8.8"})
        assert get_client_ip(request, trusted_proxies=["172.17.0.1"]) == "8.8.8.8"

    def test_no_client_object(self) -> None:
        request = self._request(None)
        assert get_client_ip(request, trusted_proxies=[]) == "unknown"


class TestGetClientIpFromScope:
    """Raw ASGI scope adapter (rate-limit middleware path)."""

    def test_untrusted_peer_ignores_forwarded_header(self) -> None:
        scope = {
            "client": ("192.168.1.10", 5000),
            "headers": [(b"x-forwarded-for", b"6.6.6.6")],
        }
        assert get_client_ip_from_scope(scope, trusted_proxies=[]) == "192.168.1.10"

    def test_trusted_peer_uses_forwarded_header(self) -> None:
        scope = {
            "client": ("172.17.0.1", 5000),
            "headers": [(b"x-forwarded-for", b"8.8.8.8, 172.17.0.1")],
        }
        assert get_client_ip_from_scope(scope, trusted_proxies=["172.17.0.1"]) == "172.17.0.1"

    def test_missing_client(self) -> None:
        assert get_client_ip_from_scope({"headers": []}, trusted_proxies=[]) == "unknown"


class TestSettingsBackedProxyList:
    """trusted_proxies defaults come from global settings (api.trusted_proxies)."""

    def test_reads_trusted_proxies_from_settings(self) -> None:
        settings = MagicMock()
        settings.api.trusted_proxies = ["10.99.0.1"]
        request = MagicMock()
        request.client = MagicMock(host="10.99.0.1")
        request.headers.get = lambda key, default=None: (
            "5.5.5.5" if key == "x-forwarded-for" else default
        )

        with patch("container.access.get_settings", return_value=settings):
            assert get_client_ip(request) == "5.5.5.5"

    def test_settings_failure_degrades_to_zero_trust(self) -> None:
        request = MagicMock()
        request.client = MagicMock(host="10.0.0.5")
        request.headers.get = lambda key, default=None: (
            "5.5.5.5" if key == "x-forwarded-for" else default
        )

        with patch("container.access.get_settings", side_effect=RuntimeError("not initialized")):
            assert get_client_ip(request) == "10.0.0.5"
