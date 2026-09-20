# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for HTML / JSON / PDF source parsers."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.parsing.document_parsers import (
    HTMLIndexParser,
    JSONApiParser,
    PDFDocumentParser,
)


def _config(url: str, source_type: str = "html") -> SourceConfig:
    """Build a SourceConfig for parser tests."""
    return SourceConfig(id="s1", name="S", url=url, source_type=source_type)


def _fetcher(status: int = 200, content: str = "") -> MagicMock:
    """Build a text-fetcher stub returning a fixed response.

    The stub exposes ``fetch_bytes`` too, since ``PDFDocumentParser`` prefers
    it; the bytes are the UTF-8 encoding of ``content``.
    """
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(return_value=(status, content, {}))
    fetcher.fetch_bytes = AsyncMock(return_value=(status, content.encode(), {}))
    return fetcher


class TestHTMLIndexParser:
    """Tests for HTMLIndexParser."""

    @pytest.mark.asyncio
    async def test_extracts_links_from_anchor_tags(self):
        """Anchor hrefs become NewsItems."""
        html = (
            "<html><body>"
            '<a href="https://example.com/news/one">One</a>'
            '<a href="/news/two">Two</a>'
            "</body></html>"
        )
        parser = HTMLIndexParser(_fetcher(200, html))

        items = await parser.parse(_config("https://example.com/index"))

        urls = [i.url for i in items]
        assert "https://example.com/news/one" in urls
        # Relative link resolved against the page URL.
        assert "https://example.com/news/two" in urls

    @pytest.mark.asyncio
    async def test_deduplicates_repeated_links(self):
        """The same href appearing twice yields one item."""
        html = (
            "<html><body>"
            '<a href="https://example.com/a">A</a>'
            '<a href="https://example.com/a">A again</a>'
            "</body></html>"
        )
        parser = HTMLIndexParser(_fetcher(200, html))

        items = await parser.parse(_config("https://example.com/index"))

        assert [i.url for i in items].count("https://example.com/a") == 1

    @pytest.mark.asyncio
    async def test_ignores_non_http_schemes(self):
        """mailto:/javascript: links are not emitted."""
        html = (
            "<html><body>"
            '<a href="mailto:test@example.com">Mail</a>'
            '<a href="javascript:void(0)">JS</a>'
            '<a href="https://example.com/real">Real</a>'
            "</body></html>"
        )
        parser = HTMLIndexParser(_fetcher(200, html))

        items = await parser.parse(_config("https://example.com/index"))

        assert [i.url for i in items] == ["https://example.com/real"]

    @pytest.mark.asyncio
    async def test_derives_placeholder_title_from_slug(self):
        """A slug path produces a readable placeholder title."""
        html = '<html><body><a href="https://example.com/some-news_slug.html">X</a></body></html>'
        parser = HTMLIndexParser(_fetcher(200, html))

        items = await parser.parse(_config("https://example.com/index"))

        assert items[0].title == "some news slug"

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        """A non-200 status yields no items instead of raising."""
        parser = HTMLIndexParser(_fetcher(404, "<html></html>"))

        assert await parser.parse(_config("https://example.com/index")) == []

    @pytest.mark.asyncio
    async def test_fetch_exception_returns_empty(self):
        """A fetch error is swallowed and yields no items."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(side_effect=RuntimeError("boom"))
        parser = HTMLIndexParser(fetcher)

        assert await parser.parse(_config("https://example.com/index")) == []

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty(self):
        """An empty body yields no items."""
        parser = HTMLIndexParser(_fetcher(200, ""))

        assert await parser.parse(_config("https://example.com/index")) == []


class TestJSONApiParser:
    """Tests for JSONApiParser."""

    @pytest.mark.asyncio
    async def test_bare_list_payload(self):
        """A top-level JSON list is parsed."""
        payload = '[{"url": "https://example.com/a", "title": "A"}]'
        parser = JSONApiParser(_fetcher(200, payload))

        items = await parser.parse(_config("https://example.com/api", "json"))

        assert len(items) == 1
        assert items[0].url == "https://example.com/a"
        assert items[0].title == "A"

    @pytest.mark.asyncio
    async def test_wrapped_list_payload(self):
        """A list nested under a known key is found."""
        payload = '{"status": "ok", "items": [{"link": "https://example.com/b"}]}'
        parser = JSONApiParser(_fetcher(200, payload))

        items = await parser.parse(_config("https://example.com/api", "json"))

        assert [i.url for i in items] == ["https://example.com/b"]

    @pytest.mark.asyncio
    async def test_entries_without_url_are_skipped(self):
        """Entries lacking a usable URL are dropped, not fatal."""
        payload = '[{"title": "no url"}, {"url": "https://example.com/c"}]'
        parser = JSONApiParser(_fetcher(200, payload))

        items = await parser.parse(_config("https://example.com/api", "json"))

        assert [i.url for i in items] == ["https://example.com/c"]

    @pytest.mark.asyncio
    async def test_iso_date_is_parsed(self):
        """An ISO 8601 date becomes a timezone-aware datetime."""
        payload = '[{"url": "https://example.com/d", "date": "2026-09-20T10:00:00Z"}]'
        parser = JSONApiParser(_fetcher(200, payload))

        items = await parser.parse(_config("https://example.com/api", "json"))

        assert items[0].publish_time == datetime(2026, 9, 20, 10, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_epoch_seconds_is_parsed(self):
        """A numeric epoch timestamp is parsed as seconds."""
        payload = '[{"url": "https://example.com/e", "timestamp": 1758362400}]'
        parser = JSONApiParser(_fetcher(200, payload))

        items = await parser.parse(_config("https://example.com/api", "json"))

        assert items[0].publish_time is not None
        assert items[0].publish_time.tzinfo is not None

    @pytest.mark.asyncio
    async def test_non_json_payload_returns_empty(self):
        """An HTML body served at a JSON URL yields no items."""
        parser = JSONApiParser(_fetcher(200, "<html>not json</html>"))

        assert await parser.parse(_config("https://example.com/api", "json")) == []

    @pytest.mark.asyncio
    async def test_unrecognized_shape_returns_empty(self):
        """A JSON object with no entry list yields no items."""
        parser = JSONApiParser(_fetcher(200, '{"foo": "bar"}'))

        assert await parser.parse(_config("https://example.com/api", "json")) == []


class TestPDFDocumentParser:
    """Tests for PDFDocumentParser."""

    @pytest.mark.asyncio
    async def test_non_pdf_content_returns_empty(self):
        """Content without a PDF signature yields no items."""
        parser = PDFDocumentParser(_fetcher(200, "just some text"))

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    @pytest.mark.asyncio
    async def test_unparseable_pdf_returns_empty(self):
        """A PDF-signature payload that cannot be parsed yields no items."""
        parser = PDFDocumentParser(_fetcher(200, "%PDF-1.4\ngarbage\n%%EOF"))

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        """A non-200 status yields no items."""
        parser = PDFDocumentParser(_fetcher(500, "%PDF-1.4"))

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    @pytest.mark.asyncio
    async def test_prefers_fetch_bytes_path(self):
        """The raw-bytes fetcher is used when available, so PDFs stay intact."""
        raw = b"%PDF-1.4\n\xe2\xe3\xcf\xd3\n%%EOF"
        fetcher = MagicMock()
        fetcher.fetch_bytes = AsyncMock(return_value=(200, raw, {}))
        fetcher.fetch = AsyncMock(side_effect=AssertionError("fetch() must not be used"))
        parser = PDFDocumentParser(fetcher)
        captured = {}

        def fake_extract(data: bytes) -> str:
            captured["raw"] = data
            return "x" * 200

        with patch.object(PDFDocumentParser, "_extract_text_safe", staticmethod(fake_extract)):
            items = await parser.parse(_config("https://example.com/a.pdf", "pdf"))

        assert len(items) == 1
        fetcher.fetch_bytes.assert_awaited_once()
        # The byte-exact payload was handed to extraction without decoding.
        assert captured["raw"] == raw

    @pytest.mark.asyncio
    async def test_falls_back_when_fetcher_has_no_fetch_bytes(self):
        """A fetcher without fetch_bytes still works via fetch()."""
        raw = "%PDF-1.4 fake"

        class LegacyFetcher:
            async def fetch(self, url, headers=None):
                return 200, raw, {}

        parser = PDFDocumentParser(LegacyFetcher())

        with patch.object(
            PDFDocumentParser, "_extract_text_safe", staticmethod(lambda data: "x" * 200)
        ):
            items = await parser.parse(_config("https://example.com/a.pdf", "pdf"))

        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_extracted_text_becomes_body(self, monkeypatch):
        """Extracted text is placed in the item body so Crawler reuses it."""
        long_text = "Paragraph about the report. " * 20
        monkeypatch.setattr(PDFDocumentParser, "_extract_text", staticmethod(lambda raw: long_text))
        parser = PDFDocumentParser(_fetcher(200, "%PDF-1.4 fake"))

        items = await parser.parse(_config("https://example.com/report.pdf", "pdf"))

        assert len(items) == 1
        assert items[0].body == long_text
        assert items[0].title == "report"
        assert items[0].url == "https://example.com/report.pdf"

    @pytest.mark.asyncio
    async def test_short_extracted_text_is_rejected(self, monkeypatch):
        """Text below the minimum length is treated as a failed extraction."""
        monkeypatch.setattr(PDFDocumentParser, "_extract_text", staticmethod(lambda raw: ""))
        parser = PDFDocumentParser(_fetcher(200, "%PDF-1.4 fake"))

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    @pytest.mark.asyncio
    async def test_non_pdf_payload_does_not_raise(self):
        """A PDF source URL serving non-PDF content degrades to a no-op.

        _extract_text raises ValueError on a missing PDF signature; parse()
        must convert that into an empty result rather than propagating and
        failing the whole crawl batch.
        """
        parser = PDFDocumentParser(_fetcher(200, "<html>login page</html>"))

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    @pytest.mark.asyncio
    async def test_fetch_error_returns_empty(self):
        """A fetch exception yields no items instead of propagating."""
        fetcher = MagicMock()
        fetcher.fetch_bytes = AsyncMock(side_effect=RuntimeError("boom"))
        parser = PDFDocumentParser(fetcher)

        assert await parser.parse(_config("https://example.com/a.pdf", "pdf")) == []

    def test_extract_text_safe_returns_empty_without_signature(self):
        """The safe wrapper swallows the signature ValueError."""
        assert PDFDocumentParser._extract_text_safe(b"not a pdf at all") == ""

    def test_extract_text_raises_without_pdf_signature(self):
        """A body without the %PDF marker is rejected explicitly."""
        with pytest.raises(ValueError, match="PDF signature"):
            PDFDocumentParser._extract_text(b"not a pdf at all")

    def test_extract_text_accepts_raw_non_utf8_bytes(self, monkeypatch):
        """Byte-exact PDF payloads reaching extraction are not mangled.

        Regression guard for the fetch layer: when the body arrived as a
        decoded str, non-UTF-8 bytes were already lost before extraction.
        With raw bytes the signature and payload survive intact.
        """
        raw = b"%PDF-1.4\n\xe2\xe3\xcf\xd3\n%%EOF"
        captured = {}

        def fake_pypdf(content):
            captured["raw"] = content
            return "x" * 200

        monkeypatch.setattr(PDFDocumentParser, "_extract_with_pypdf", staticmethod(fake_pypdf))

        PDFDocumentParser._extract_text(raw)

        assert captured["raw"] == raw
        assert captured["raw"].endswith(b"%%EOF")


class TestPDFExtractionBackends:
    """Tests for the real pypdf / pdfplumber extraction backends.

    The parser shipped with both backends imported lazily and neither
    declared as a dependency, so PDF sources could not extract anything. The
    deps now live in the ``pdf-extraction`` extra; these tests pin the actual
    extraction behaviour and the precedence between backends.
    """

    @staticmethod
    def _build_pdf(
        text: str,
        path,
    ) -> bytes:
        """Write a minimal one-page PDF containing ``text`` and return it."""
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        stream = f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode()

        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            stream,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]

        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"

        xref_pos = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
        ).encode()

        path.write_bytes(bytes(out))
        return bytes(out)

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """A real PDF whose text is long enough to pass the length floor."""
        body = (
            "Weaver PDF extraction backend check. This sentence exists purely "
            "to push the extracted character count above the minimum threshold "
            "enforced by the parser, so the text is kept rather than discarded."
        )
        payload = self._build_pdf(body, tmp_path / "sample.pdf")
        return payload, body

    def test_pypdf_extracts_real_text(self, sample_pdf):
        """The pypdf backend returns the document's text."""
        pytest.importorskip("pypdf")
        payload, body = sample_pdf

        extracted = PDFDocumentParser._extract_with_pypdf(payload)

        assert body[:40] in extracted

    def test_pdfplumber_extracts_real_text(self, sample_pdf):
        """The pdfplumber backend returns the document's text."""
        pytest.importorskip("pdfplumber")
        payload, body = sample_pdf

        extracted = PDFDocumentParser._extract_with_pdfplumber(payload)

        assert body[:40] in extracted

    def test_extract_text_uses_real_backend(self, sample_pdf):
        """_extract_text yields real content when a backend is installed."""
        pytest.importorskip("pypdf")
        payload, body = sample_pdf

        extracted = PDFDocumentParser._extract_text(payload)

        assert len(extracted) >= 100
        assert body[:40] in extracted

    def test_pypdf_preferred_over_pdfplumber(self, monkeypatch, sample_pdf):
        """pypdf is tried first; pdfplumber is only a fallback."""
        payload, _ = sample_pdf
        calls = {"pypdf": 0, "pdfplumber": 0}

        def fake_pypdf(_raw):
            calls["pypdf"] += 1
            return "y" * 200

        def fake_pdfplumber(_raw):
            calls["pdfplumber"] += 1
            return "z" * 200

        monkeypatch.setattr(PDFDocumentParser, "_extract_with_pypdf", staticmethod(fake_pypdf))
        monkeypatch.setattr(
            PDFDocumentParser, "_extract_with_pdfplumber", staticmethod(fake_pdfplumber)
        )

        PDFDocumentParser._extract_text(payload)

        assert calls == {"pypdf": 1, "pdfplumber": 0}

    def test_pdfplumber_runs_when_pypdf_yields_nothing(self, monkeypatch, sample_pdf):
        """A pdfplumber fallback fires only when pypdf returns empty."""
        payload, _ = sample_pdf
        calls = {"pypdf": 0, "pdfplumber": 0}

        def fake_pypdf(_raw):
            calls["pypdf"] += 1
            return ""

        def fake_pdfplumber(_raw):
            calls["pdfplumber"] += 1
            return "z" * 200

        monkeypatch.setattr(PDFDocumentParser, "_extract_with_pypdf", staticmethod(fake_pypdf))
        monkeypatch.setattr(
            PDFDocumentParser, "_extract_with_pdfplumber", staticmethod(fake_pdfplumber)
        )

        result = PDFDocumentParser._extract_text(payload)

        assert calls == {"pypdf": 1, "pdfplumber": 1}
        assert len(result) == 200

    @pytest.mark.asyncio
    async def test_parse_returns_item_with_real_pdf(self, tmp_path, sample_pdf):
        """End-to-end: a real PDF becomes one NewsItem with the text as body."""
        pytest.importorskip("pypdf")
        payload, body = sample_pdf
        fetcher = MagicMock()
        fetcher.fetch_bytes = AsyncMock(return_value=(200, payload, {}))
        parser = PDFDocumentParser(fetcher)

        items = await parser.parse(_config("https://example.com/report.pdf", "pdf"))

        assert len(items) == 1
        assert items[0].body.startswith("Weaver PDF extraction backend check")
        assert body[:40] in items[0].body

    def test_missing_backends_return_empty_not_raise(self, monkeypatch):
        """With both backends unavailable the parser degrades to ""."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name in {"pypdf", "pdfplumber"}:
                raise ImportError(f"no module named {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        assert PDFDocumentParser._extract_with_pypdf(b"%PDF-1.4\n") == ""
        assert PDFDocumentParser._extract_with_pdfplumber(b"%PDF-1.4\n") == ""
