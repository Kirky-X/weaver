# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for the byte-exact fetch path (fetch_bytes + decode_response_text).

``fetch`` decodes the body to ``str``; for binary payloads such as PDFs no
encoding can be inferred for a non-text media type, so httpx falls back to
UTF-8 and corrupts non-UTF-8 bytes. ``fetch_bytes`` exists so binary callers
avoid that decode entirely, while ``fetch`` keeps its previous behaviour.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.fetching.httpx_fetcher import (
    HttpxFetcher,
    decode_response_text,
)


def _mock_response(content: bytes, headers: dict[str, str] | None = None) -> MagicMock:
    """Build a response stub exposing ``.content`` like a real httpx Response."""
    response = MagicMock()
    response.status_code = 200
    response.content = content
    response.text = content.decode("utf-8", errors="replace")
    response.headers = headers or {}
    response.history = []
    response.http_version = "HTTP/2"
    return response


class TestDecodeResponseText:
    """Tests for the text decoder used by fetch()."""

    def test_defaults_to_utf8_without_charset(self):
        """No Content-Type charset means UTF-8."""
        body = "héllo".encode()

        assert decode_response_text(body, {"content-type": "text/html"}) == "héllo"

    def test_honours_declared_charset(self):
        """A declared non-UTF-8 charset is honoured (GBK page)."""
        body = "中文测试".encode("gbk")

        result = decode_response_text(body, {"content-type": "text/html; charset=gbk"})

        assert result == "中文测试"

    def test_charset_lookup_is_case_insensitive(self):
        """Header name lookup ignores case."""
        body = b"abc"

        assert decode_response_text(body, {"Content-Type": "text/plain"}) == "abc"

    def test_unknown_charset_falls_back_to_utf8(self):
        """An unregistered charset name falls back instead of raising."""
        body = b"abc"

        result = decode_response_text(
            body, {"content-type": "text/html; charset=bogus-charset-xyz"}
        )

        assert result == "abc"

    def test_undecodable_bytes_are_replaced_not_raised(self):
        """Invalid bytes are replaced rather than raising UnicodeDecodeError."""
        body = b"\xff\xfe\x00\x01"

        result = decode_response_text(body, {"content-type": "application/pdf"})

        assert isinstance(result, str)

    def test_missing_content_type_uses_default(self):
        """An empty header set still decodes."""
        assert decode_response_text(b"ok", {}) == "ok"


class TestFetchBytes:
    """Tests for HttpxFetcher.fetch_bytes."""

    @pytest.mark.asyncio
    async def test_returns_raw_bytes_undecoded(self):
        """Non-UTF-8 bytes survive untouched through fetch_bytes."""
        raw = b"%PDF-1.4\n\xe2\xe3\xcf\xd3\n%%EOF"
        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(raw)
            status, body, _headers = await fetcher.fetch_bytes("https://example.com/a.pdf")

        assert status == 200
        assert body == raw

    @pytest.mark.asyncio
    async def test_fetch_and_fetch_bytes_agree_on_utf8_text(self):
        """For plain UTF-8 text both entry points yield the same string."""
        raw = "中文内容".encode()
        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(raw, {"Content-Type": "text/html"})
            _status, text, _ = await fetcher.fetch("https://example.com")

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(raw, {"Content-Type": "text/html"})
            _status, body, _ = await fetcher.fetch_bytes("https://example.com")

        assert body.decode("utf-8") == text

    @pytest.mark.asyncio
    async def test_fetch_matches_httpx_text_semantics_for_gbk(self):
        """fetch() decodes a GBK page correctly, like response.text did."""
        body = "中文测试".encode("gbk")
        fetcher = HttpxFetcher()

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(
                body, {"Content-Type": "text/html; charset=gbk"}
            )
            _status, text, _ = await fetcher.fetch("https://example.com")

        assert text == "中文测试"

    @pytest.mark.asyncio
    async def test_pre_validated_skips_url_validator(self):
        """fetch_bytes honours pre_validated like fetch does."""
        fetcher = HttpxFetcher()
        validator = MagicMock()
        validator.validate = AsyncMock()
        fetcher._url_validator = validator

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(b"%PDF-1.4")
            await fetcher.fetch_bytes("https://example.com", pre_validated=True)

        validator.validate.assert_not_called()

    @pytest.mark.asyncio
    async def test_validates_url_by_default(self):
        """Without pre_validated, the SSRF validator runs."""
        fetcher = HttpxFetcher()
        validator = MagicMock()
        validator.validate = AsyncMock()
        validator.validate.return_value = MagicMock(is_safe=True)
        fetcher._url_validator = validator

        with patch.object(fetcher._client, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = _mock_response(b"%PDF-1.4")
            await fetcher.fetch_bytes("https://example.com")

        validator.validate.assert_called_once_with("https://example.com")


class TestResponseBodyBytesFallback:
    """The internal body helper tolerates a text-only response double."""

    def test_uses_content_when_present(self):
        """A real response exposes .content; it is used verbatim."""
        from modules.ingestion.fetching.httpx_fetcher import _response_body_bytes

        response = MagicMock()
        response.content = b"\x00\x01\xff"

        assert _response_body_bytes(response) == b"\x00\x01\xff"

    def test_falls_back_to_text_encoding(self):
        """A double exposing only .text still produces bytes."""
        from modules.ingestion.fetching.httpx_fetcher import _response_body_bytes

        response = MagicMock(spec=["text"])
        response.text = "abc"

        assert _response_body_bytes(response) == b"abc"
