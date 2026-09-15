# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for SSRF protection in httpx_fetcher.py.

Verifies that validate() return value is properly checked and SSRFError
is raised when URL is blocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security.models import CheckResult, CheckSource, URLRisk, ValidationResult
from core.security.validation.ssrf import SSRFError
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher


def _make_validation_result(is_safe: bool, risk: URLRisk = URLRisk.SAFE) -> ValidationResult:
    """Helper to create a ValidationResult."""
    return ValidationResult(
        url="http://example.com",
        risk=risk,
        is_safe=is_safe,
        checks=[
            CheckResult(
                source=CheckSource.SSRF,
                risk=risk,
                message="test",
            )
        ],
    )


@pytest.fixture
def mock_url_validator():
    """Create a mock URL validator."""
    validator = AsyncMock()
    return validator


@pytest.fixture
def fetcher_with_validator(mock_url_validator):
    """Create HttpxFetcher with mock validator."""
    fetcher = HttpxFetcher(url_validator=mock_url_validator)
    return fetcher


class TestSSRFProtection:
    """Test SSRF protection in fetch() and post()."""

    @pytest.mark.asyncio
    async def test_fetch_raises_ssrf_error_on_blocked_url(
        self, fetcher_with_validator, mock_url_validator
    ):
        """Verify fetch() raises SSRFError when validate() returns is_safe=False."""
        mock_url_validator.validate.return_value = _make_validation_result(
            is_safe=False, risk=URLRisk.BLOCKED
        )

        with pytest.raises(SSRFError) as exc_info:
            await fetcher_with_validator.fetch("http://169.254.169.254")

        assert "blocked" in str(exc_info.value).lower()
        mock_url_validator.validate.assert_called_once_with("http://169.254.169.254")

    @pytest.mark.asyncio
    async def test_fetch_proceeds_on_safe_url(self, fetcher_with_validator, mock_url_validator):
        """Verify fetch() proceeds normally when validate() returns is_safe=True."""
        mock_url_validator.validate.return_value = _make_validation_result(is_safe=True)

        # Replace the real httpx client with a mock to avoid network calls
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}
        mock_response.history = []
        mock_response.http_version = "HTTP/1.1"

        mock_request = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send.return_value = mock_response
        fetcher_with_validator._client = mock_client

        result = await fetcher_with_validator.fetch("https://example.com")

        assert result[0] == 200
        mock_url_validator.validate.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_skips_validation_when_pre_validated(
        self, fetcher_with_validator, mock_url_validator
    ):
        """Verify fetch() skips validation when pre_validated=True."""
        # Replace the real httpx client with a mock
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}
        mock_response.history = []
        mock_response.http_version = "HTTP/1.1"

        mock_request = MagicMock()
        mock_client.build_request.return_value = mock_request
        mock_client.send.return_value = mock_response
        fetcher_with_validator._client = mock_client

        await fetcher_with_validator.fetch("https://example.com", pre_validated=True)

        mock_url_validator.validate.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_raises_ssrf_error_on_blocked_url(
        self, fetcher_with_validator, mock_url_validator
    ):
        """Verify post() raises SSRFError when validate() returns is_safe=False."""
        mock_url_validator.validate.return_value = _make_validation_result(
            is_safe=False, risk=URLRisk.BLOCKED
        )

        with pytest.raises(SSRFError) as exc_info:
            await fetcher_with_validator.post("http://169.254.169.254", json_data={"key": "value"})

        assert "blocked" in str(exc_info.value).lower()
        mock_url_validator.validate.assert_called_once_with("http://169.254.169.254")

    @pytest.mark.asyncio
    async def test_post_proceeds_on_safe_url(self, fetcher_with_validator, mock_url_validator):
        """Verify post() proceeds normally when validate() returns is_safe=True."""
        mock_url_validator.validate.return_value = _make_validation_result(is_safe=True)

        # Replace the real httpx client with a mock
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}
        mock_response.history = []
        mock_response.http_version = "HTTP/1.1"

        mock_client.post.return_value = mock_response
        fetcher_with_validator._client = mock_client

        result = await fetcher_with_validator.post(
            "https://example.com", json_data={"key": "value"}
        )

        assert result[0] == 200
        mock_url_validator.validate.assert_called_once_with("https://example.com")
