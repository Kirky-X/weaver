# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for URLhausClient."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security.malicious_url.urlhaus_client import URLhausClient, URLhausResponse, URLhausStatus
from core.security.models import CheckSource, URLRisk


class TestURLhausClient:
    """Tests for URLhaus API client."""

    @pytest.fixture
    def mock_fetcher(self) -> MagicMock:
        """Create mock HTTP fetcher."""
        fetcher = MagicMock()
        fetcher.post = AsyncMock()
        return fetcher

    @pytest.fixture
    def client(self, mock_fetcher: MagicMock) -> URLhausClient:
        """Create URLhaus client instance."""
        return URLhausClient(api_key="test-api-key", fetcher=mock_fetcher)

    # ── Response Parsing ────────────────────────────────────────────────

    def test_parse_safe_response(self, client: URLhausClient) -> None:
        """Parse response for safe URL."""
        response = URLhausResponse(
            status=URLhausStatus.SAFE,
        )
        assert response.status == URLhausStatus.SAFE

    def test_parse_malicious_response(self, client: URLhausClient) -> None:
        """Parse response for malicious URL."""
        response = URLhausResponse(
            status=URLhausStatus.MALICIOUS,
            threat_type="malware_download",
            threat_url="https://malicious.example.com",
        )
        assert response.status == URLhausStatus.MALICIOUS
        assert response.threat_type == "malware_download"

    # ── API Calls ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_safe_url(self, client: URLhausClient, mock_fetcher: MagicMock) -> None:
        """Check a safe URL (not found in database)."""
        mock_fetcher.post.return_value = (
            200,
            '{"query_status": "no_results"}',
            {},
        )

        response = await client.check("https://example.com")

        assert response.status == URLhausStatus.SAFE
        mock_fetcher.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_malicious_url(
        self, client: URLhausClient, mock_fetcher: MagicMock
    ) -> None:
        """Check a malicious URL (found in database)."""
        mock_fetcher.post.return_value = (
            200,
            '{"query_status": "ok", "url": "https://malicious.example.com", "threat": "malware_download"}',
            {},
        )

        response = await client.check("https://malicious.example.com")

        assert response.status == URLhausStatus.MALICIOUS
        assert response.threat_type == "malware_download"

    @pytest.mark.asyncio
    async def test_check_url_not_found(
        self, client: URLhausClient, mock_fetcher: MagicMock
    ) -> None:
        """Check URL not in database."""
        mock_fetcher.post.return_value = (
            200,
            '{"query_status": "no_results"}',
            {},
        )

        response = await client.check("https://unknown.example.com")

        assert response.status == URLhausStatus.SAFE

    @pytest.mark.asyncio
    async def test_check_http_error(self, client: URLhausClient, mock_fetcher: MagicMock) -> None:
        """Handle HTTP error."""
        mock_fetcher.post.return_value = (
            500,
            "Internal Server Error",
            {},
        )

        response = await client.check("https://example.com")

        assert response.status == URLhausStatus.ERROR

    @pytest.mark.asyncio
    async def test_check_rate_limited(self, client: URLhausClient, mock_fetcher: MagicMock) -> None:
        """Handle rate limit."""
        mock_fetcher.post.return_value = (
            429,
            "Too Many Requests",
            {},
        )

        response = await client.check("https://example.com")

        assert response.status == URLhausStatus.ERROR
        assert "Rate limited" in response.error_message

    @pytest.mark.asyncio
    async def test_check_timeout(self, client: URLhausClient, mock_fetcher: MagicMock) -> None:
        """Handle timeout error."""
        mock_fetcher.post.side_effect = TimeoutError("Request timed out")

        response = await client.check("https://example.com")

        assert response.status == URLhausStatus.ERROR

    @pytest.mark.asyncio
    async def test_check_connection_error(
        self, client: URLhausClient, mock_fetcher: MagicMock
    ) -> None:
        """Handle connection error."""
        mock_fetcher.post.side_effect = ConnectionError("Connection failed")

        response = await client.check("https://example.com")

        assert response.status == URLhausStatus.ERROR

    @pytest.mark.asyncio
    async def test_check_no_api_key(self, mock_fetcher: MagicMock) -> None:
        """Handle missing API key."""
        client_no_key = URLhausClient(api_key="", fetcher=mock_fetcher)

        response = await client_no_key.check("https://example.com")

        assert response.status == URLhausStatus.ERROR
        assert "API key" in response.error_message

    # ── Result Conversion ────────────────────────────────────────────────

    def test_to_check_result_safe(self, client: URLhausClient) -> None:
        """Convert safe response to check result."""
        response = URLhausResponse(
            status=URLhausStatus.SAFE,
        )

        result = client.to_check_result(response)

        assert result.source == CheckSource.URLHAUS_API
        assert result.risk == URLRisk.SAFE

    def test_to_check_result_malicious(self, client: URLhausClient) -> None:
        """Convert malicious response to check result."""
        response = URLhausResponse(
            status=URLhausStatus.MALICIOUS,
            threat_type="malware_download",
            threat_url="https://malicious.example.com",
        )

        result = client.to_check_result(response)

        assert result.source == CheckSource.URLHAUS_API
        assert result.risk == URLRisk.BLOCKED

    def test_to_check_result_error(self, client: URLhausClient) -> None:
        """Convert error response to check result."""
        response = URLhausResponse(
            status=URLhausStatus.ERROR,
            error_message="Connection failed",
        )

        result = client.to_check_result(response)

        assert result.source == CheckSource.URLHAUS_API
        # Error should return LOW to trigger local checks
        assert result.risk == URLRisk.LOW
        assert result.should_fallback is True
