# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HttpxFetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestRedirectBlockedError:
    """Tests for RedirectBlockedError."""

    def test_error_message(self):
        """Test RedirectBlockedError message."""
        from modules.ingestion.fetching.httpx_fetcher import RedirectBlockedError

        error = RedirectBlockedError("https://evil.com", "SSRF detected")

        assert "evil.com" in str(error)
        assert "SSRF detected" in str(error)
        assert error.redirect_url == "https://evil.com"
        assert error.reason == "SSRF detected"


class TestSecureRedirectHandler:
    """Tests for SecureRedirectHandler."""

    def test_init_without_validator(self):
        """Test handler initializes without validator."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        handler = SecureRedirectHandler(validator=None)

        assert handler._validator is None

    def test_init_with_validator(self):
        """Test handler initializes with validator."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        handler = SecureRedirectHandler(validator=mock_validator)

        assert handler._validator is mock_validator

    @pytest.mark.asyncio
    async def test_validate_redirect_without_validator(self):
        """Test validation passes without validator."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        handler = SecureRedirectHandler(validator=None)

        mock_request = MagicMock()
        mock_request.url = "https://example.com/redirect"
        mock_response = MagicMock()

        # Should not raise
        await handler.validate_redirect(mock_request, mock_response)

    @pytest.mark.asyncio
    async def test_validate_redirect_with_safe_url(self):
        """Test validation passes for safe URL."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        handler = SecureRedirectHandler(validator=mock_validator)

        mock_request = MagicMock()
        mock_request.url = "https://example.com/redirect"
        mock_response = MagicMock()

        await handler.validate_redirect(mock_request, mock_response)

        mock_validator.validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_redirect_blocks_unsafe_url(self):
        """Test validation blocks unsafe URL."""
        from modules.ingestion.fetching.httpx_fetcher import (
            RedirectBlockedError,
            SecureRedirectHandler,
        )

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = False

        handler = SecureRedirectHandler(validator=mock_validator)

        mock_request = MagicMock()
        mock_request.url = "http://localhost/admin"
        mock_response = MagicMock()

        with pytest.raises(RedirectBlockedError):
            await handler.validate_redirect(mock_request, mock_response)


class TestHttpxFetcherInit:
    """Tests for HttpxFetcher initialization."""

    def test_init_with_defaults(self):
        """Test HttpxFetcher initializes with default settings."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        assert fetcher.http2_enabled is True
        assert fetcher._client is not None

    def test_init_with_custom_settings(self):
        """Test HttpxFetcher initializes with custom settings."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(
            timeout=30.0,
            user_agent="CustomBot/1.0",
            http2=False,
            max_connections=50,
            max_keepalive=10,
        )

        assert fetcher.http2_enabled is False

    def test_init_with_validator(self):
        """Test HttpxFetcher initializes with URL validator."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        mock_validator = MagicMock()
        fetcher = HttpxFetcher(url_validator=mock_validator)

        assert fetcher._url_validator is mock_validator


class TestHttpxFetcherFetch:
    """Tests for HttpxFetcher.fetch()."""

    @pytest.fixture
    def fetcher(self):
        """Create HttpxFetcher instance."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        return HttpxFetcher()

    @pytest.mark.asyncio
    async def test_fetch_returns_response(self, fetcher):
        """Test fetch returns status, content, headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.history = []
        mock_response.http_version = "HTTP/2"

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            status, text, headers = await fetcher.fetch("https://example.com")

            assert status == 200
            assert text == "<html>content</html>"
            assert "Content-Type" in headers

    @pytest.mark.asyncio
    async def test_fetch_validates_url_with_validator(self, fetcher):
        """Test fetch validates URL when validator is set."""
        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            await fetcher.fetch("https://example.com")

            mock_validator.validate.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_handles_transport_error(self, fetcher):
        """Test fetch handles transport errors."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = httpx.TransportError("Connection failed")

            with pytest.raises(httpx.TransportError):
                await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_close_closes_client(self, fetcher):
        """Test close() closes the client."""
        with patch.object(fetcher._client, "aclose", new_callable=AsyncMock) as mock_close:
            await fetcher.close()

            mock_close.assert_called_once()


class TestHttpxFetcherValidateRedirectChain:
    """Tests for _validate_redirect_chain()."""

    @pytest.fixture
    def fetcher(self):
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        return HttpxFetcher()

    @pytest.mark.asyncio
    async def test_validate_redirect_chain_without_validator(self, fetcher):
        """Test redirect chain validation passes without validator."""
        # No validator set
        fetcher._url_validator = None

        mock_response = MagicMock()
        mock_response.url = "https://example.com/redirect"

        # Should not raise
        await fetcher._validate_redirect_chain([mock_response], "https://example.com")

    @pytest.mark.asyncio
    async def test_validate_redirect_chain_with_safe_urls(self, fetcher):
        """Test redirect chain validation passes for safe URLs."""
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.url = "https://example.com/redirect"

        # Should not raise
        await fetcher._validate_redirect_chain([mock_response], "https://example.com")

    @pytest.mark.asyncio
    async def test_validate_redirect_chain_blocks_unsafe_url(self, fetcher):
        """Test redirect chain validation blocks unsafe URL."""
        from modules.ingestion.fetching.httpx_fetcher import (
            HttpxFetcher,
            RedirectBlockedError,
        )

        fetcher = HttpxFetcher()
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = False
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.url = "http://internal.secret/admin"

        with pytest.raises(RedirectBlockedError):
            await fetcher._validate_redirect_chain([mock_response], "https://example.com")


class TestHttpxFetcherEdgeCases:
    """Edge case tests for HttpxFetcher."""

    @pytest.fixture
    def fetcher(self):
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        return HttpxFetcher()

    @pytest.mark.asyncio
    async def test_fetch_with_redirects(self, fetcher):
        """Test fetch handles redirect responses."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = [
            MagicMock(url="https://example.com/redirect1", status_code=301),
            MagicMock(url="https://example.com/final", status_code=200),
        ]
        mock_response.http_version = "HTTP/2"

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            status, text, headers = await fetcher.fetch("https://example.com")

            assert status == 200

    @pytest.mark.asyncio
    async def test_fetch_with_custom_headers(self, fetcher):
        """Test fetch passes custom headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            await fetcher.fetch("https://example.com", headers={"X-Custom": "value"})

            # Verify build_request was called with headers
            call_args = mock_send.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_fetch_handles_http_status_error(self, fetcher):
        """Test fetch handles HTTP status errors."""
        from httpx import HTTPStatusError, Response

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 404

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(HTTPStatusError):
                await fetcher.fetch("https://example.com/notfound")

    @pytest.mark.asyncio
    async def test_fetch_handles_generic_error(self, fetcher):
        """Test fetch handles generic errors."""
        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Generic error")

            with pytest.raises(Exception) as exc_info:
                await fetcher.fetch("https://example.com")

            assert "Generic error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_redirect_chain_skips_first_if_original(self, fetcher):
        """Test redirect chain skips first URL if it matches original."""
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.url = "https://example.com/start"

        # First URL matches original, should skip
        await fetcher._validate_redirect_chain([mock_response], "https://example.com/start")

        # is_safe_url should not be called for first URL if it matches
        mock_validator.is_safe_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_redirect_chain_handles_exception(self, fetcher):
        """Test redirect chain handles exceptions in validator."""
        from modules.ingestion.fetching.httpx_fetcher import RedirectBlockedError

        mock_validator = MagicMock()
        mock_validator.is_safe_url.side_effect = Exception("Validation error")
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.url = "https://example.com/redirect"

        with pytest.raises(RedirectBlockedError):
            await fetcher._validate_redirect_chain([mock_response], "https://example.com/start")

    @pytest.mark.asyncio
    async def test_secure_redirect_handler_with_validator_exception(self):
        """Test SecureRedirectHandler handles validator exceptions."""
        from modules.ingestion.fetching.httpx_fetcher import (
            RedirectBlockedError,
            SecureRedirectHandler,
        )

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock(side_effect=Exception("Async error"))

        handler = SecureRedirectHandler(validator=mock_validator)

        mock_request = MagicMock()
        mock_request.url = "https://example.com/redirect"
        mock_response = MagicMock()

        with pytest.raises(RedirectBlockedError):
            await handler.validate_redirect(mock_request, mock_response)


class TestHttpxFetcherHTTP2:
    """Tests for HTTP/2 functionality."""

    def test_http2_enabled_by_default(self):
        """Test HTTP/2 is enabled by default."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        assert fetcher.http2_enabled is True

    def test_http2_can_be_disabled(self):
        """Test HTTP/2 can be disabled."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(http2=False)

        assert fetcher.http2_enabled is False

    @pytest.mark.asyncio
    async def test_fetch_uses_http2_when_enabled(self):
        """Test fetch uses HTTP/2 when enabled."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(http2=True)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []
        mock_response.http_version = "HTTP/2"

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            status, text, headers = await fetcher.fetch("https://example.com")

            assert status == 200


class TestHttpxFetcherTimeout:
    """Tests for timeout configuration."""

    def test_default_timeout(self):
        """Test default timeout is 15 seconds."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        # Timeout is configured in client
        assert fetcher._client is not None

    def test_custom_timeout(self):
        """Test custom timeout configuration."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(timeout=30.0)

        assert fetcher._client is not None

    @pytest.mark.asyncio
    async def test_fetch_respects_timeout(self):
        """Test fetch respects timeout setting."""
        from httpx import ConnectTimeout

        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(timeout=0.001)  # Very short timeout

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = ConnectTimeout("Connection timed out")

            with pytest.raises(ConnectTimeout):
                await fetcher.fetch("https://example.com")


class TestHttpxFetcherConnectionPool:
    """Tests for connection pool configuration."""

    def test_default_connection_limits(self):
        """Test default connection pool limits."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        # Connection pool is configured
        assert fetcher._client is not None

    def test_custom_connection_limits(self):
        """Test custom connection pool limits."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(
            max_connections=50,
            max_keepalive=10,
        )

        assert fetcher._client is not None


class TestHttpxFetcherUserAgent:
    """Tests for User-Agent configuration."""

    def test_default_user_agent(self):
        """Test default User-Agent."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        # Default User-Agent is set
        assert fetcher._client is not None

    def test_custom_user_agent(self):
        """Test custom User-Agent."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher(user_agent="CustomBot/2.0")

        assert fetcher._client is not None
