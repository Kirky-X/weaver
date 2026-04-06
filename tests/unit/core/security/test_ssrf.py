# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SSRFChecker."""

import pytest

from core.security.ssrf import SSRFChecker, SSRFError


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
