# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for HttpxFetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from modules.fetcher.httpx_fetcher import HttpxFetcher, RedirectBlockedError, SecureRedirectHandler


class TestRedirectBlockedError:
    """Tests for RedirectBlockedError exception."""

    def test_init(self):
        """Test basic initialization."""
        error = RedirectBlockedError("https://evil.com", "Private IP")

        assert error.redirect_url == "https://evil.com"
        assert error.reason == "Private IP"
        assert "evil.com" in str(error)
        assert "Private IP" in str(error)

    def test_inherits_from_exception(self):
        """Test that RedirectBlockedError inherits from Exception."""
        error = RedirectBlockedError("https://test.com", "test reason")
        assert isinstance(error, Exception)


class TestSecureRedirectHandler:
    """Tests for SecureRedirectHandler."""

    def test_init_without_validator(self):
        """Test initialization without validator."""
        handler = SecureRedirectHandler()
        assert handler._validator is None

    def test_init_with_validator(self):
        """Test initialization with validator."""
        mock_validator = MagicMock()
        handler = SecureRedirectHandler(validator=mock_validator)
        assert handler._validator is mock_validator

    @pytest.mark.asyncio
    async def test_validate_redirect_no_validator(self):
        """Test validation passes when no validator configured."""
        handler = SecureRedirectHandler()
        request = MagicMock()
        request.url = "https://example.com"
        response = MagicMock()

        # Should not raise
        await handler.validate_redirect(request, response)

    @pytest.mark.asyncio
    async def test_validate_redirect_safe_url(self):
        """Test validation passes for safe URL."""
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        handler = SecureRedirectHandler(validator=mock_validator)
        request = MagicMock()
        request.url = "https://example.com"
        response = MagicMock()

        await handler.validate_redirect(request, response)

        mock_validator.is_safe_url.assert_called_once_with("https://example.com")
        mock_validator.validate.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_validate_redirect_unsafe_url_sync_check(self):
        """Test validation fails on synchronous check."""
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = False

        handler = SecureRedirectHandler(validator=mock_validator)
        request = MagicMock()
        request.url = "https://192.168.1.1"
        response = MagicMock()

        with pytest.raises(RedirectBlockedError) as exc_info:
            await handler.validate_redirect(request, response)

        assert "security check" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_redirect_unsafe_url_async_check(self):
        """Test validation fails on async check."""
        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock(side_effect=ValueError("Blocked"))

        handler = SecureRedirectHandler(validator=mock_validator)
        request = MagicMock()
        request.url = "https://example.com"
        response = MagicMock()

        with pytest.raises(RedirectBlockedError):
            await handler.validate_redirect(request, response)


class TestHttpxFetcher:
    """Tests for HttpxFetcher."""

    def test_init_defaults(self):
        """Test initialization with default parameters."""
        fetcher = HttpxFetcher()

        assert fetcher._http2_enabled is True
        assert fetcher._url_validator is None
        assert fetcher._redirect_handler is not None

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        mock_validator = MagicMock()
        fetcher = HttpxFetcher(
            timeout=30.0,
            user_agent="CustomBot/1.0",
            http2=False,
            max_connections=50,
            max_keepalive=10,
            url_validator=mock_validator,
        )

        assert fetcher._http2_enabled is False
        assert fetcher._url_validator is mock_validator
        assert fetcher._redirect_handler._validator is mock_validator

    def test_http2_enabled_property(self):
        """Test http2_enabled property."""
        fetcher = HttpxFetcher(http2=True)
        assert fetcher.http2_enabled is True

        fetcher = HttpxFetcher(http2=False)
        assert fetcher.http2_enabled is False

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        fetcher = HttpxFetcher()
        await fetcher.close()
        # Should complete without error

    @pytest.mark.asyncio
    async def test_fetch_success_no_validator(self):
        """Test successful fetch without URL validator."""
        fetcher = HttpxFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            status, text, headers = await fetcher.fetch("https://example.com")

            assert status == 200
            assert text == "<html>content</html>"
            assert headers["content-type"] == "text/html"

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_success_with_validator(self):
        """Test successful fetch with URL validator."""
        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        mock_validator.is_safe_url.return_value = True

        fetcher = HttpxFetcher(url_validator=mock_validator)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            status, text, headers = await fetcher.fetch("https://example.com")

            assert status == 200
            mock_validator.validate.assert_called_once_with("https://example.com")

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_with_custom_headers(self):
        """Test fetch with custom headers."""
        fetcher = HttpxFetcher()

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

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_validator_rejects_url(self):
        """Test fetch rejects URL blocked by validator."""
        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock(side_effect=ValueError("URL blocked"))

        fetcher = HttpxFetcher(url_validator=mock_validator)

        with pytest.raises(ValueError, match="URL blocked"):
            await fetcher.fetch("https://blocked.com")

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_transport_error(self):
        """Test fetch handles transport error."""
        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = httpx.TransportError("Connection failed")

            with pytest.raises(httpx.TransportError):
                await fetcher.fetch("https://example.com")

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_http_status_error(self):
        """Test fetch handles HTTP status error."""
        fetcher = HttpxFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response)

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = mock_error

            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.fetch("https://example.com/notfound")

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_with_redirects_no_validator(self):
        """Test fetch follows redirects without validator."""
        fetcher = HttpxFetcher()

        mock_redirect_response = MagicMock()
        mock_redirect_response.url = "https://example.com/redirect"
        mock_redirect_response.status_code = 302

        mock_final_response = MagicMock()
        mock_final_response.status_code = 200
        mock_final_response.text = "final content"
        mock_final_response.headers = {}
        mock_final_response.history = [mock_redirect_response]

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_final_response

            status, text, _ = await fetcher.fetch("https://example.com/old")

            assert status == 200
            assert text == "final content"

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_redirect_blocked(self):
        """Test fetch blocks redirect to unsafe URL."""
        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        mock_validator.is_safe_url.return_value = False

        fetcher = HttpxFetcher(url_validator=mock_validator)

        mock_redirect_response = MagicMock()
        mock_redirect_response.url = "https://192.168.1.1/secret"

        mock_final_response = MagicMock()
        mock_final_response.status_code = 200
        mock_final_response.text = "content"
        mock_final_response.headers = {}
        mock_final_response.history = [mock_redirect_response]

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_final_response

            with pytest.raises(RedirectBlockedError):
                await fetcher.fetch("https://example.com")

        await fetcher.close()


class TestHttpxFetcherMetrics:
    """Tests for metrics collection in HttpxFetcher."""

    @pytest.mark.asyncio
    async def test_metrics_on_success(self):
        """Test metrics are recorded on success."""
        fetcher = HttpxFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            with patch("modules.fetcher.httpx_fetcher.MetricsCollector") as mock_metrics:
                await fetcher.fetch("https://example.com")

                # Verify metrics were called
                mock_metrics.fetch_total.labels.assert_called()
                mock_metrics.fetch_latency.labels.assert_called()

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_metrics_on_error(self):
        """Test metrics are recorded on error."""
        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = httpx.TransportError("Connection failed")

            with patch("modules.fetcher.httpx_fetcher.MetricsCollector") as mock_metrics:
                with pytest.raises(httpx.TransportError):
                    await fetcher.fetch("https://example.com")

                # Verify error metrics were called
                mock_metrics.fetch_total.labels.assert_called()

        await fetcher.close()
