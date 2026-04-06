# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for URL security validator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security import SSRFError, URLValidationError, URLValidator, URLValidatorConfig
from core.security.models import CheckSource, URLRisk


class TestURLValidator:
    """Tests for URLValidator facade."""

    @pytest.fixture
    def mock_fetcher(self) -> MagicMock:
        """Create mock HTTP fetcher."""
        fetcher = MagicMock()
        fetcher.get = AsyncMock(return_value=(200, "", {}))
        fetcher.post = AsyncMock(return_value=(200, "{}", {}))
        return fetcher

    @pytest.fixture
    def config(self) -> URLValidatorConfig:
        """Create validator config."""
        return URLValidatorConfig(
            enabled=True,
            urlhaus_api_key="",  # Disabled
            phishtank_enabled=False,
            heuristic_enabled=False,
            ssl_verify_enabled=False,
            cache_enabled=False,
        )

    @pytest.fixture
    def validator(self, config: URLValidatorConfig, mock_fetcher: MagicMock) -> URLValidator:
        """Create a URL validator instance."""
        return URLValidator(config=config, fetcher=mock_fetcher)

    # ── Valid URL Tests ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_validate_valid_http_url(self, validator: URLValidator) -> None:
        """Valid HTTP URL should pass validation."""
        url = "http://example.com/path"
        result = await validator.validate(url)
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_validate_valid_https_url(self, validator: URLValidator) -> None:
        """Valid HTTPS URL should pass validation."""
        url = "https://example.com/path?query=value"
        result = await validator.validate(url)
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_validate_valid_url_with_port(self, validator: URLValidator) -> None:
        """Valid URL with port should pass validation."""
        url = "https://example.com:8443/path"
        result = await validator.validate(url)
        assert result.is_safe is True

    # ── Blocked Scheme Tests ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_file_scheme(self, validator: URLValidator) -> None:
        """file:// scheme should be blocked."""
        result = await validator.validate("file:///etc/passwd")
        assert result.risk == URLRisk.BLOCKED
        assert result.is_safe is False

    @pytest.mark.asyncio
    async def test_block_ftp_scheme(self, validator: URLValidator) -> None:
        """ftp:// scheme should be blocked."""
        result = await validator.validate("ftp://example.com/file")
        assert result.risk == URLRisk.BLOCKED

    @pytest.mark.asyncio
    async def test_block_gopher_scheme(self, validator: URLValidator) -> None:
        """gopher:// scheme should be blocked."""
        result = await validator.validate("gopher://example.com/")
        assert result.risk == URLRisk.BLOCKED

    # ── Blocked IP Range Tests ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_private_ip_10_range(self, validator: URLValidator) -> None:
        """10.x.x.x private IP range should be blocked."""
        result = await validator.validate("http://10.0.0.1/")
        assert result.risk == URLRisk.BLOCKED
        assert "blocked" in result.primary_reason.lower() if result.primary_reason else True

    @pytest.mark.asyncio
    async def test_block_private_ip_172_range(self, validator: URLValidator) -> None:
        """172.16.x.x private IP range should be blocked."""
        result = await validator.validate("http://172.16.0.1/")
        assert result.risk == URLRisk.BLOCKED

    @pytest.mark.asyncio
    async def test_block_private_ip_192_range(self, validator: URLValidator) -> None:
        """192.168.x.x private IP range should be blocked."""
        result = await validator.validate("http://192.168.1.1/")
        assert result.risk == URLRisk.BLOCKED

    @pytest.mark.asyncio
    async def test_block_localhost(self, validator: URLValidator) -> None:
        """127.x.x.x loopback should be blocked."""
        result = await validator.validate("http://127.0.0.1/")
        assert result.risk == URLRisk.BLOCKED

    @pytest.mark.asyncio
    async def test_block_0_0_0_0(self, validator: URLValidator) -> None:
        """0.0.0.0 should be blocked."""
        result = await validator.validate("http://0.0.0.0/")
        assert result.risk == URLRisk.BLOCKED

    # ── Cloud Metadata Tests ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_block_aws_metadata(self, validator: URLValidator) -> None:
        """AWS metadata endpoint should be blocked."""
        result = await validator.validate("http://169.254.169.254/latest/meta-data/")
        assert result.risk == URLRisk.BLOCKED

    # ── Malformed URL Tests ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_reject_url_without_scheme(self, validator: URLValidator) -> None:
        """URL without scheme should be rejected."""
        result = await validator.validate("example.com/path")
        assert result.risk == URLRisk.BLOCKED

    # ── Disabled Validator Tests ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_disabled_validator_returns_safe(self, mock_fetcher: MagicMock) -> None:
        """Disabled validator should return safe for all URLs."""
        config = URLValidatorConfig(enabled=False)
        validator = URLValidator(config=config, fetcher=mock_fetcher)

        result = await validator.validate("http://192.168.1.1/")
        assert result.is_safe is True


class TestURLValidationError:
    """Tests for URLValidationError (SSRFError alias)."""

    def test_error_message(self) -> None:
        """Error should include message."""
        error = URLValidationError("Test error message")
        assert error.message == "Test error message"

    def test_error_with_url(self) -> None:
        """Error can include URL for context."""
        error = URLValidationError("Test error", url="http://example.com")
        assert error.url == "http://example.com"
        assert "Test error" in str(error)

    def test_is_alias_for_ssrf_error(self) -> None:
        """URLValidationError should be alias for SSRFError."""
        assert URLValidationError is SSRFError
