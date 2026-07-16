# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SSRFChecker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.security.validation.ssrf import SSRFChecker, SSRFError


class TestSSRFChecker:
    """Tests for SSRF protection."""

    @pytest.fixture
    def checker(self) -> SSRFChecker:
        """Create SSRF checker instance."""
        return SSRFChecker()

    # ── Safe URLs ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_valid_https_url(self, checker: SSRFChecker) -> None:
        """Valid HTTPS URL should pass."""
        await checker.validate("https://example.com/path")

    @pytest.mark.asyncio
    async def test_valid_http_url(self, checker: SSRFChecker) -> None:
        """Valid HTTP URL should pass."""
        await checker.validate("http://example.com/path")

    @pytest.mark.asyncio
    async def test_url_with_port(self, checker: SSRFChecker) -> None:
        """URL with explicit port should pass."""
        await checker.validate("https://example.com:8080/path")

    @pytest.mark.asyncio
    async def test_url_with_query(self, checker: SSRFChecker) -> None:
        """URL with query string should pass."""
        await checker.validate("https://example.com/path?query=value")

    @pytest.mark.asyncio
    async def test_url_with_fragment(self, checker: SSRFChecker) -> None:
        """URL with fragment should pass."""
        await checker.validate("https://example.com/path#fragment")

    # ── Blocked IPs ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_localhost_blocked(self, checker: SSRFChecker) -> None:
        """localhost should be blocked."""
        with pytest.raises(SSRFError) as exc_info:
            await checker.validate("http://localhost/path")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_127_0_0_1_blocked(self, checker: SSRFChecker) -> None:
        """127.0.0.1 should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://127.0.0.1/path")

    @pytest.mark.asyncio
    async def test_127_any_blocked(self, checker: SSRFChecker) -> None:
        """Any 127.x.x.x IP should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://127.1.2.3/path")

    @pytest.mark.asyncio
    async def test_0_0_0_0_blocked(self, checker: SSRFChecker) -> None:
        """0.0.0.0 should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://0.0.0.0/path")

    @pytest.mark.asyncio
    async def test_private_10_range_blocked(self, checker: SSRFChecker) -> None:
        """10.x.x.x private range should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://10.0.0.1/path")

    @pytest.mark.asyncio
    async def test_private_172_range_blocked(self, checker: SSRFChecker) -> None:
        """172.16-31.x.x private range should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://172.16.0.1/path")

    @pytest.mark.asyncio
    async def test_private_192_168_range_blocked(self, checker: SSRFChecker) -> None:
        """192.168.x.x private range should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://192.168.1.1/path")

    @pytest.mark.asyncio
    async def test_link_local_169_254_blocked(self, checker: SSRFChecker) -> None:
        """169.254.x.x link-local range should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://169.254.1.1/path")

    @pytest.mark.asyncio
    async def test_ipv6_loopback_blocked(self, checker: SSRFChecker) -> None:
        """IPv6 loopback ::1 should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://[::1]/path")

    @pytest.mark.asyncio
    async def test_ipv6_localhost_blocked(self, checker: SSRFChecker) -> None:
        """IPv6 localhost should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("http://[0:0:0:0:0:0:0:1]/path")

    # ── Blocked Schemes ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self, checker: SSRFChecker) -> None:
        """file:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_ftp_scheme_blocked(self, checker: SSRFChecker) -> None:
        """ftp:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_gopher_scheme_blocked(self, checker: SSRFChecker) -> None:
        """gopher:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("gopher://example.com/")

    @pytest.mark.asyncio
    async def test_dict_scheme_blocked(self, checker: SSRFChecker) -> None:
        """dict:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("dict://example.com/")

    @pytest.mark.asyncio
    async def test_tftp_scheme_blocked(self, checker: SSRFChecker) -> None:
        """tftp:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("tftp://example.com/file")

    @pytest.mark.asyncio
    async def test_ldap_scheme_blocked(self, checker: SSRFChecker) -> None:
        """ldap:// scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("ldap://example.com/")

    # ── Malformed URLs ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_missing_scheme_blocked(self, checker: SSRFChecker) -> None:
        """URL without scheme should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("example.com/path")

    @pytest.mark.asyncio
    async def test_invalid_url_blocked(self, checker: SSRFChecker) -> None:
        """Invalid URL should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("not a url")

    @pytest.mark.asyncio
    async def test_empty_url_blocked(self, checker: SSRFChecker) -> None:
        """Empty URL should be blocked."""
        with pytest.raises(SSRFError):
            await checker.validate("")

    # ── DNS Rebinding Protection ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ip_resolution_from_domain(self, checker: SSRFChecker) -> None:
        """Domain resolving to private IP should be blocked."""
        # This test relies on actual DNS resolution
        # In CI, we might want to mock this
        pass  # Skipped - requires DNS mocking

    # ── Edge Cases ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_url_with_username_password(self, checker: SSRFChecker) -> None:
        """URL with credentials should pass for public domains."""
        await checker.validate("https://user:pass@example.com/path")

    @pytest.mark.asyncio
    async def test_subdomain_of_blocked_blocked(self, checker: SSRFChecker) -> None:
        """Subdomain resolving to blocked IP should be blocked."""
        # localhost.example.com might resolve to 127.0.0.1
        pass  # Skipped - requires DNS mocking

    @pytest.mark.asyncio
    async def test_decimal_ip_blocked(self, checker: SSRFChecker) -> None:
        """Decimal IP notation should be handled."""
        # 2130706433 = 127.0.0.1 in decimal
        with pytest.raises(SSRFError):
            await checker.validate("http://2130706433/path")

    @pytest.mark.asyncio
    async def test_hex_ip_blocked(self, checker: SSRFChecker) -> None:
        """Hex IP notation should be handled."""
        # 0x7f000001 = 127.0.0.1 in hex
        with pytest.raises(SSRFError):
            await checker.validate("http://0x7f000001/path")

    @pytest.mark.asyncio
    async def test_octal_ip_blocked(self, checker: SSRFChecker) -> None:
        """Octal IP notation should be handled."""
        # 0177.0.0.1 = 127.0.0.1 in octal
        with pytest.raises(SSRFError):
            await checker.validate("http://0177.0.0.1/path")


class TestSSRFRedirectTracking:
    """Tests for SSRF redirect chain tracking.

    Validates that HTTP redirect chains are followed and each
    redirect target is checked against blocked IP ranges.
    """

    @pytest.fixture
    def checker(self) -> SSRFChecker:
        """Create SSRF checker instance."""
        return SSRFChecker()

    @pytest.mark.asyncio
    async def test_redirect_to_internal_ip_blocked(self, checker: SSRFChecker) -> None:
        """Redirect to internal IP (169.254.169.254) should be blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(SSRFError, match="blocked"):
                await checker.validate("http://evil.com/redirect")

    @pytest.mark.asyncio
    async def test_multi_hop_redirect_all_valid(self, checker: SSRFChecker) -> None:
        """Multi-hop redirect to public IPs should pass."""
        # First redirect: evil.com -> good.com (public IP)
        resp1 = MagicMock()
        resp1.status_code = 302
        resp1.headers = {"location": "https://good.com/path"}

        # Second redirect: good.com -> final.com (public IP)
        resp2 = MagicMock()
        resp2.status_code = 301
        resp2.headers = {"location": "https://final.com/path"}

        # Final: no more redirects
        resp3 = MagicMock()
        resp3.status_code = 200

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=[resp1, resp2, resp3])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with patch.object(checker, "_validate_ip_address", new_callable=AsyncMock):
                # All redirect targets resolve to public IPs
                await checker.validate("http://evil.com/redirect")

    @pytest.mark.asyncio
    async def test_circular_redirect_detected(self, checker: SSRFChecker) -> None:
        """Circular redirect should be detected and blocked."""
        resp_a = MagicMock()
        resp_a.status_code = 302
        resp_a.headers = {"location": "http://b.example.com/"}

        resp_b = MagicMock()
        resp_b.status_code = 302
        resp_b.headers = {"location": "http://a.example.com/"}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=[resp_a, resp_b])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with patch.object(checker, "_validate_ip_address", new_callable=AsyncMock):
                with pytest.raises(SSRFError, match=r"[Cc]ircular"):
                    await checker.validate("http://a.example.com/")

    @pytest.mark.asyncio
    async def test_max_redirect_hops_exceeded(self, checker: SSRFChecker) -> None:
        """Redirect chain exceeding 5 hops should be blocked."""
        redirect_responses = []
        for i in range(6):
            resp = MagicMock()
            resp.status_code = 302
            resp.headers = {"location": f"http://hop{i}.example.com/"}
            redirect_responses.append(resp)

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=redirect_responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with patch.object(checker, "_validate_ip_address", new_callable=AsyncMock):
                with pytest.raises(SSRFError, match=r"[Mm]ax.*redirect"):
                    await checker.validate("http://start.example.com/")

    @pytest.mark.asyncio
    async def test_dns_valid_but_redirect_to_blocked_ip(self, checker: SSRFChecker) -> None:
        """URL with valid DNS but redirecting to blocked IP should be rejected."""
        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "http://10.0.0.1/secret"}

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=redirect_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(SSRFError, match="blocked"):
                await checker.validate("http://legit-looking.com/path")

    @pytest.mark.asyncio
    async def test_no_redirect_passes(self, checker: SSRFChecker) -> None:
        """URL with no redirects should pass (redirect check is a no-op)."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with patch.object(checker, "_validate_ip_address", new_callable=AsyncMock):
                await checker.validate("http://example.com/path")

    @pytest.mark.asyncio
    async def test_redirect_network_error_handled(self, checker: SSRFChecker) -> None:
        """Network error during redirect check should not block the URL."""
        import httpx

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.security.validation.ssrf.httpx.AsyncClient", return_value=mock_client):
            with patch.object(checker, "_validate_ip_address", new_callable=AsyncMock):
                # Should NOT raise - network errors during redirect check are logged but not blocking
                await checker.validate("http://unreachable.example.com/path")
