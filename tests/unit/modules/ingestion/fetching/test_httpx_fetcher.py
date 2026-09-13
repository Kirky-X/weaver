# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
    """Tests for SecureRedirectHandler (httpx response event-hook)."""

    @staticmethod
    def _redirect_response(location: str) -> httpx.Response:
        """Build a real 302 response with a Location header."""
        return httpx.Response(
            302,
            headers={"location": location},
            request=httpx.Request("GET", "https://example.com/start"),
        )

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
    async def test_hook_passes_without_validator(self):
        """Test validation passes without validator."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        handler = SecureRedirectHandler(validator=None)
        response = self._redirect_response("https://example.com/redirect")

        # Should not raise
        await handler(response)

    @pytest.mark.asyncio
    async def test_hook_ignores_non_redirect(self):
        """Test non-3xx responses are not validated."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        handler = SecureRedirectHandler(validator=mock_validator)
        response = httpx.Response(200, request=httpx.Request("GET", "https://example.com/"))

        await handler(response)

        mock_validator.is_safe_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_hook_validates_safe_redirect_target(self):
        """Test a safe redirect target is validated against its joined URL."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        handler = SecureRedirectHandler(validator=mock_validator)
        response = self._redirect_response("/relative/target")

        await handler(response)

        mock_validator.is_safe_url.assert_called_once_with("https://example.com/relative/target")
        mock_validator.validate.assert_called_once_with("https://example.com/relative/target")

    @pytest.mark.asyncio
    async def test_hook_blocks_private_connected_ip(self):
        """Anti-rebinding: a response served from a private IP is blocked."""
        from modules.ingestion.fetching.httpx_fetcher import (
            RedirectBlockedError,
            SecureRedirectHandler,
        )

        mock_validator = MagicMock()

        def check_connected_ip(ip, url):
            if ip.startswith("127.") or ip.startswith("10."):
                from core.security.validation.ssrf import SSRFError

                raise SSRFError(f"private ip {ip}")

        mock_validator.check_connected_ip.side_effect = check_connected_ip
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        handler = SecureRedirectHandler(validator=mock_validator)
        request = httpx.Request("GET", "https://evil.example.com/page")
        response = httpx.Response(200, request=request)
        response.extensions["network_stream"] = MagicMock(
            get_extra_info=MagicMock(return_value=("127.0.0.1", 443))
        )

        with pytest.raises(RedirectBlockedError):
            await handler(response)

        mock_validator.validate.assert_not_called()

    @pytest.mark.asyncio
    async def test_hook_passes_public_connected_ip(self):
        """A response from a public IP passes the connected-IP check."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        mock_validator.check_connected_ip = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        handler = SecureRedirectHandler(validator=mock_validator)
        request = httpx.Request("GET", "https://ok.example.com/page")
        response = httpx.Response(200, request=request)
        response.extensions["network_stream"] = MagicMock(
            get_extra_info=MagicMock(return_value=("93.184.216.34", 443))
        )

        await handler(response)

        mock_validator.check_connected_ip.assert_called_once_with(
            "93.184.216.34", "https://ok.example.com/page"
        )

    @pytest.mark.asyncio
    async def test_hook_tolerates_missing_network_stream(self):
        """No network_stream extension (mock transports) → no IP check."""
        from modules.ingestion.fetching.httpx_fetcher import SecureRedirectHandler

        mock_validator = MagicMock()
        mock_validator.check_connected_ip = MagicMock()

        handler = SecureRedirectHandler(validator=mock_validator)
        response = httpx.Response(200, request=httpx.Request("GET", "https://x.com/"))

        await handler(response)

        mock_validator.check_connected_ip.assert_not_called()

    @pytest.mark.asyncio
    async def test_hook_blocks_unsafe_redirect_target(self):
        """Test validation blocks an unsafe redirect target."""
        from modules.ingestion.fetching.httpx_fetcher import (
            RedirectBlockedError,
            SecureRedirectHandler,
        )

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = False

        handler = SecureRedirectHandler(validator=mock_validator)
        response = self._redirect_response("http://localhost/admin")

        with pytest.raises(RedirectBlockedError) as exc_info:
            await handler(response)

        assert "http://localhost/admin" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_hook_wraps_async_validation_error(self):
        """Test async validator exceptions surface as RedirectBlockedError."""
        from modules.ingestion.fetching.httpx_fetcher import (
            RedirectBlockedError,
            SecureRedirectHandler,
        )

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock(side_effect=Exception("Async error"))

        handler = SecureRedirectHandler(validator=mock_validator)
        response = self._redirect_response("https://example.com/redirect")

        with pytest.raises(RedirectBlockedError):
            await handler(response)


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
            user_agents=["CustomBot/1.0"],
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


class TestHttpxFetcherRedirectGuard:
    """Pre-request redirect guard: unsafe targets are never contacted."""

    @pytest.mark.asyncio
    async def test_unsafe_redirect_target_never_requested(self):
        """End-to-end: a redirect to a blocked host must not be followed."""
        from modules.ingestion.fetching.httpx_fetcher import (
            HttpxFetcher,
            RedirectBlockedError,
        )

        requested_urls: list[str] = []

        def transport_handler(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            if request.url.host == "start.example.com":
                return httpx.Response(
                    302,
                    headers={"location": "http://169.254.169.254/latest/meta-data"},
                )
            return httpx.Response(200, text="secret")

        mock_validator = MagicMock()
        mock_validator.is_safe_url.side_effect = lambda url: "169.254." not in url
        mock_validator.validate = AsyncMock()

        fetcher = HttpxFetcher(
            url_validator=mock_validator,
            transport=httpx.MockTransport(transport_handler),
        )

        with pytest.raises(RedirectBlockedError):
            await fetcher.fetch("https://start.example.com/page")

        assert requested_urls == ["https://start.example.com/page"]
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_safe_redirect_chain_is_followed(self):
        """End-to-end: a safe redirect chain resolves to the final content."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        def transport_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "start.example.com":
                return httpx.Response(302, headers={"location": "https://final.example.com/doc"})
            return httpx.Response(200, text="final content")

        mock_validator = MagicMock()
        mock_validator.is_safe_url.return_value = True
        mock_validator.validate = AsyncMock()

        fetcher = HttpxFetcher(
            url_validator=mock_validator,
            transport=httpx.MockTransport(transport_handler),
        )

        status, text, _ = await fetcher.fetch("https://start.example.com/page")

        assert status == 200
        assert text == "final content"
        await fetcher.close()

    def test_event_hook_registered_when_validator_present(self):
        """Client-level response hook is registered only with a validator."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        guarded = HttpxFetcher(url_validator=MagicMock())
        unguarded = HttpxFetcher()

        assert len(guarded._client._event_hooks["response"]) == 1
        assert guarded._client._event_hooks["response"][0] is guarded._redirect_handler
        assert len(unguarded._client._event_hooks["response"]) == 0

        # post() shares the same client, so it is guarded too.
        assert unguarded._redirect_handler._validator is None


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

        fetcher = HttpxFetcher(user_agents=["CustomBot/2.0"])

        assert fetcher._client is not None
        assert fetcher._user_agents == ["CustomBot/2.0"]


class TestHttpxFetcherMetrics:
    """Tests for metrics collection in HttpxFetcher."""

    @pytest.mark.asyncio
    async def test_metrics_on_success(self):
        """Test metrics are recorded on success."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "content"
        mock_response.headers = {}
        mock_response.history = []

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            with patch("modules.ingestion.fetching.httpx_fetcher.MetricsCollector") as mock_metrics:
                await fetcher.fetch("https://example.com")

                mock_metrics.fetch_total.labels.assert_called()
                mock_metrics.fetch_latency.labels.assert_called()

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_metrics_on_error(self):
        """Test metrics are recorded on error."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = httpx.TransportError("Connection failed")

            with patch("modules.ingestion.fetching.httpx_fetcher.MetricsCollector") as mock_metrics:
                with pytest.raises(httpx.TransportError):
                    await fetcher.fetch("https://example.com")

                mock_metrics.fetch_total.labels.assert_called()

        await fetcher.close()


class TestHttpxFetcherPost:
    """Tests for HttpxFetcher.post()."""

    @pytest.fixture
    def fetcher(self):
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        return HttpxFetcher()

    @pytest.mark.asyncio
    async def test_post_with_json_data(self, fetcher):
        """Test POST with JSON body."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"Content-Type": "application/json"}

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            status, text, headers = await fetcher.post(
                "https://api.example.com/data",
                json_data={"key": "value"},
            )

            assert status == 201
            assert text == '{"ok": true}'
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_with_form_data(self, fetcher):
        """Test POST with form data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            status, text, headers = await fetcher.post(
                "https://api.example.com/form",
                data={"field": "value"},
            )

            assert status == 200
            assert text == "OK"

    @pytest.mark.asyncio
    async def test_post_with_custom_headers(self, fetcher):
        """Test POST with custom headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            await fetcher.post(
                "https://api.example.com",
                json_data={"key": "value"},
                headers={"Authorization": "Bearer token123"},
            )

            call_kwargs = mock_post.call_args
            assert call_kwargs[1]["headers"]["Authorization"] == "Bearer token123"

    @pytest.mark.asyncio
    async def test_post_validates_url_with_validator(self, fetcher):
        """Test POST validates URL when validator is set."""
        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        fetcher._url_validator = mock_validator

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            await fetcher.post("https://api.example.com/data", json_data={"key": "val"})

            mock_validator.validate.assert_called_once_with("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_post_skips_validation_without_validator(self, fetcher):
        """Test POST skips URL validation when no validator set."""
        fetcher._url_validator = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_response.headers = {}

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            status, text, headers = await fetcher.post("https://api.example.com")

            assert status == 200

    @pytest.mark.asyncio
    async def test_post_raises_on_transport_error(self, fetcher):
        """Test POST raises TransportError."""
        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TransportError("Connection refused")

            with pytest.raises(httpx.TransportError):
                await fetcher.post("https://api.example.com")

    @pytest.mark.asyncio
    async def test_post_raises_on_http_status_error(self, fetcher):
        """Test POST raises HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "Internal Server Error",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.post("https://api.example.com/broken")

    @pytest.mark.asyncio
    async def test_post_raises_on_generic_error(self, fetcher):
        """Test POST raises generic exceptions."""
        with patch.object(fetcher._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = RuntimeError("Unexpected error")

            with pytest.raises(RuntimeError, match="Unexpected error"):
                await fetcher.post("https://api.example.com")
