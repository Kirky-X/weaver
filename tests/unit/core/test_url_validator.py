# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for URL security validator."""

from __future__ import annotations

import pytest

from core.security import URLValidationError, URLValidator


class TestURLValidator:
    """Tests for URLValidator SSRF protection."""

    @pytest.fixture
    def validator(self) -> URLValidator:
        """Create a URL validator instance."""
        return URLValidator()

    # ── Valid URL Tests ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_validate_valid_http_url(self, validator: URLValidator) -> None:
        """Valid HTTP URL should pass validation."""
        url = "http://example.com/path"
        result = await validator.validate(url)
        assert result == url

    @pytest.mark.asyncio
    async def test_validate_valid_https_url(self, validator: URLValidator) -> None:
        """Valid HTTPS URL should pass validation."""
        url = "https://example.com/path?query=value"
        result = await validator.validate(url)
        assert result == url

    @pytest.mark.asyncio
    async def test_validate_valid_url_with_port(self, validator: URLValidator) -> None:
        """Valid URL with port should pass validation."""
        url = "https://example.com:8443/path"
        result = await validator.validate(url)
        assert result == url

    # ── Blocked Scheme Tests ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_file_scheme(self, validator: URLValidator) -> None:
        """file:// scheme should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("file:///etc/passwd")
        assert "not allowed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_ftp_scheme(self, validator: URLValidator) -> None:
        """ftp:// scheme should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("ftp://example.com/file")
        assert "not allowed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_javascript_scheme(self, validator: URLValidator) -> None:
        """javascript: scheme should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("javascript:alert(1)")
        assert "not allowed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_data_scheme(self, validator: URLValidator) -> None:
        """data: scheme should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("data:text/html,<script>alert(1)</script>")
        assert "not allowed" in str(exc_info.value).lower()

    # ── Blocked IP Range Tests ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_private_ip_10_range(self, validator: URLValidator) -> None:
        """10.x.x.x private IP range should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://10.0.0.1/")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_private_ip_172_range(self, validator: URLValidator) -> None:
        """172.16.x.x private IP range should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://172.16.0.1/")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_private_ip_192_range(self, validator: URLValidator) -> None:
        """192.168.x.x private IP range should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://192.168.1.1/")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_localhost(self, validator: URLValidator) -> None:
        """127.x.x.x loopback should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://127.0.0.1/")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_0_0_0_0(self, validator: URLValidator) -> None:
        """0.0.0.0 should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://0.0.0.0/")
        assert "blocked" in str(exc_info.value).lower()

    # ── Cloud Metadata Tests ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_aws_metadata(self, validator: URLValidator) -> None:
        """AWS metadata endpoint should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://169.254.169.254/latest/meta-data/")
        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_block_gcp_metadata_hostname(self, validator: URLValidator) -> None:
        """GCP metadata hostname should be blocked."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://metadata.google.internal/computeMetadata/v1/")
        assert "blocked" in str(exc_info.value).lower()

    # ── Malformed URL Tests ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_reject_url_without_scheme(self, validator: URLValidator) -> None:
        """URL without scheme should be rejected."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("example.com/path")
        assert "scheme" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_reject_url_without_hostname(self, validator: URLValidator) -> None:
        """URL without hostname should be rejected."""
        with pytest.raises(URLValidationError) as exc_info:
            await validator.validate("http://")
        assert "hostname" in str(exc_info.value).lower()

    # ── Synchronous Safety Check Tests ──────────────────────────────────────

    def test_is_safe_url_valid(self, validator: URLValidator) -> None:
        """is_safe_url should return True for valid URLs."""
        assert validator.is_safe_url("https://example.com/") is True

    def test_is_safe_url_blocked_scheme(self, validator: URLValidator) -> None:
        """is_safe_url should return False for blocked schemes."""
        assert validator.is_safe_url("file:///etc/passwd") is False

    def test_is_safe_url_blocked_ip(self, validator: URLValidator) -> None:
        """is_safe_url should return False for blocked IPs."""
        assert validator.is_safe_url("http://192.168.1.1/") is False

    def test_is_safe_url_aws_metadata(self, validator: URLValidator) -> None:
        """is_safe_url should return False for AWS metadata."""
        assert validator.is_safe_url("http://169.254.169.254/") is False


class TestURLValidationError:
    """Tests for URLValidationError."""

    def test_error_message(self) -> None:
        """Error should include message."""
        error = URLValidationError("Test error message")
        assert error.message == "Test error message"

    def test_error_with_url(self) -> None:
        """Error can include URL for context."""
        error = URLValidationError("Test error", url="http://example.com")
        assert error.url == "http://example.com"
        assert "Test error" in str(error)
