# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for parse_bing_html (web search HTML parser).

TDD Red phase: tests fail until ``parse_bing_html`` is implemented in
``src/modules/search/web/html_parser.py`` (T005 Green).

The fixture HTML (``fixtures/bing_sample.html``) is a stripped-down Bing
search result page covering: valid results, results missing href,
results missing title, whitespace padding, and non-result list items
that must be ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.search.web.html_parser import parse_bing_html
from modules.search.web.protocol import BingSearchResult

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    """Load a fixture HTML file by name."""
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


class TestParseBingHtmlBasic:
    """Basic parsing tests — verify the happy path."""

    def test_parse_returns_list_of_bing_search_result(self) -> None:
        """Return value must be list[BingSearchResult]."""
        html = _load_fixture("bing_sample.html")
        results = parse_bing_html(html)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, BingSearchResult)

    def test_parse_extracts_at_least_one_result_from_fixture(self) -> None:
        """Fixture has 3 valid results (5 b_algo, 2 skipped) — must extract ≥3."""
        html = _load_fixture("bing_sample.html")
        results = parse_bing_html(html)
        assert len(results) >= 3, f"expected ≥3 results, got {len(results)}"

    def test_parse_extracts_title_url_snippet_correctly(self) -> None:
        """First result must have correct title, url, snippet from fixture."""
        html = _load_fixture("bing_sample.html")
        results = parse_bing_html(html)
        first = results[0]
        assert first.title == "First Test Article Title"
        assert first.url == "https://example.com/article1"
        assert "First snippet text" in first.snippet
        assert "highlighted" in first.snippet  # HTML stripped, text preserved

    def test_parse_returns_multiple_results_in_order(self) -> None:
        """Multiple valid results must be returned in document order."""
        html = _load_fixture("bing_sample.html")
        results = parse_bing_html(html)
        titles = [r.title for r in results]
        # 3 valid results in fixture (articles 1, 2, 3 — the 4th and 5th
        # b_algo are skipped due to missing href/title)
        assert "First Test Article Title" in titles
        assert "Second Test Article Title" in titles
        assert "Third Article With Whitespace" in titles  # whitespace stripped


class TestParseBingHtmlEdgeCases:
    """Edge cases — verify graceful handling of malformed input."""

    def test_parse_empty_html_returns_empty_list(self) -> None:
        """Empty string HTML must return [] (not raise)."""
        assert parse_bing_html("") == []

    def test_parse_html_without_b_algo_returns_empty_list(self) -> None:
        """HTML lacking .b_algo nodes must return [] (not raise)."""
        html = "<html><body><p>no results here</p></body></html>"
        assert parse_bing_html(html) == []

    def test_parse_none_input_returns_empty_list(self) -> None:
        """None input must return [] (defensive — caller may pass None)."""
        assert parse_bing_html(None) == []  # type: ignore[arg-type]

    def test_parse_skips_results_without_href(self) -> None:
        """b_algo entries with <a> but no href must be skipped."""
        html = """
        <li class="b_algo">
          <h2><a>Title without href</a></h2>
          <div class="b_caption"><p>snippet</p></div>
        </li>
        """
        results = parse_bing_html(html)
        assert results == []

    def test_parse_skips_results_without_title_text(self) -> None:
        """b_algo entries with empty <a> text must be skipped."""
        html = """
        <li class="b_algo">
          <h2><a href="https://example.com"></a></h2>
          <div class="b_caption"><p>snippet</p></div>
        </li>
        """
        results = parse_bing_html(html)
        assert results == []

    def test_parse_strips_whitespace_from_title_and_snippet(self) -> None:
        """Title and snippet must be .strip()'d."""
        html = """
        <li class="b_algo">
          <h2><a href="https://example.com">   Spaced Title   </a></h2>
          <div class="b_caption"><p>  Spaced snippet  </p></div>
        </li>
        """
        results = parse_bing_html(html)
        assert len(results) == 1
        assert results[0].title == "Spaced Title"
        assert results[0].snippet == "Spaced snippet"

    def test_parse_handles_missing_snippet_gracefully(self) -> None:
        """b_algo without .b_caption p must still yield result with empty snippet."""
        html = """
        <li class="b_algo">
          <h2><a href="https://example.com">Title Without Snippet</a></h2>
        </li>
        """
        results = parse_bing_html(html)
        assert len(results) == 1
        assert results[0].title == "Title Without Snippet"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == ""

    def test_parse_ignores_non_b_algo_list_items(self) -> None:
        """li.b_no_result and li.b_pag must NOT be parsed as results."""
        html = """
        <li class="b_no_result">No results</li>
        <li class="b_pag">Pagination</li>
        <li class="b_algo">
          <h2><a href="https://example.com">Real Result</a></h2>
          <div class="b_caption"><p>real snippet</p></div>
        </li>
        """
        results = parse_bing_html(html)
        assert len(results) == 1
        assert results[0].title == "Real Result"


class TestParseBingHtmlMaxResults:
    """Tests for max_results truncation (T006 will use this)."""

    def test_parse_respects_max_results_argument(self) -> None:
        """When max_results is provided, returned list length must be ≤ max_results."""
        html = _load_fixture("bing_sample.html")
        # Fixture has 3 valid results; cap at 2
        results = parse_bing_html(html, max_results=2)
        assert len(results) <= 2
        # First 2 in document order
        assert results[0].title == "First Test Article Title"
        assert results[1].title == "Second Test Article Title"

    def test_parse_max_results_zero_returns_empty_list(self) -> None:
        """max_results=0 must return empty list."""
        html = _load_fixture("bing_sample.html")
        assert parse_bing_html(html, max_results=0) == []

    def test_parse_max_results_negative_returns_empty_list(self) -> None:
        """Negative max_results must return empty list (defensive)."""
        html = _load_fixture("bing_sample.html")
        assert parse_bing_html(html, max_results=-1) == []

    def test_parse_max_results_larger_than_actual_returns_all(self) -> None:
        """max_results larger than result count returns all results."""
        html = _load_fixture("bing_sample.html")
        results = parse_bing_html(html, max_results=100)
        # 3 valid results in fixture
        assert len(results) == 3

    def test_parse_default_max_results_returns_all(self) -> None:
        """Default max_results (None or unspecified) returns all valid results."""
        html = _load_fixture("bing_sample.html")
        results_no_arg = parse_bing_html(html)
        results_none_arg = parse_bing_html(html, max_results=None)
        assert len(results_no_arg) == 3
        assert len(results_none_arg) == 3


class TestParseBingHtmlSecurity:
    """Security hardening tests — URL scheme whitelist + DoS size cap.

    These cover the MEDIUM findings from the T004-T006 security review:
    - M1: non-http(s) schemes (javascript:/data:/file:) must be rejected
    - M2: HTML exceeding _MAX_HTML_SIZE must be rejected before parsing
    """

    def test_parse_rejects_javascript_scheme_url(self) -> None:
        """javascript: scheme URLs must be skipped (XSS prevention)."""
        html = """
        <li class="b_algo">
          <h2><a href="javascript:alert('xss')">XSS Title</a></h2>
          <div class="b_caption"><p>snippet</p></div>
        </li>
        <li class="b_algo">
          <h2><a href="https://example.com/safe">Safe Title</a></h2>
          <div class="b_caption"><p>safe snippet</p></div>
        </li>
        """
        results = parse_bing_html(html)
        assert len(results) == 1
        assert results[0].title == "Safe Title"
        assert results[0].url == "https://example.com/safe"

    def test_parse_rejects_data_scheme_url(self) -> None:
        """data: scheme URLs must be skipped (XSS / payload injection)."""
        html = """
        <li class="b_algo">
          <h2><a href="data:text/html,<script>alert(1)</script>">Data URL</a></h2>
        </li>
        """
        results = parse_bing_html(html)
        assert results == []

    def test_parse_rejects_file_scheme_url(self) -> None:
        """file: scheme URLs must be skipped (local file access prevention)."""
        html = """
        <li class="b_algo">
          <h2><a href="file:///etc/passwd">File URL</a></h2>
        </li>
        """
        results = parse_bing_html(html)
        assert results == []

    def test_parse_rejects_vbscript_and_blob_schemes(self) -> None:
        """vbscript: and blob: schemes must be skipped (IE/legacy XSS)."""
        html = """
        <li class="b_algo">
          <h2><a href="vbscript:msgbox('xss')">VBScript</a></h2>
        </li>
        <li class="b_algo">
          <h2><a href="blob:https://example.com/abc">Blob URL</a></h2>
        </li>
        """
        results = parse_bing_html(html)
        assert results == []

    def test_parse_accepts_http_and_https_schemes(self) -> None:
        """Both http:// and https:// schemes must be accepted."""
        html = """
        <li class="b_algo">
          <h2><a href="http://example.com/http">HTTP Result</a></h2>
        </li>
        <li class="b_algo">
          <h2><a href="https://example.com/https">HTTPS Result</a></h2>
        </li>
        """
        results = parse_bing_html(html)
        assert len(results) == 2
        assert results[0].url == "http://example.com/http"
        assert results[1].url == "https://example.com/https"

    def test_parse_rejects_oversized_html(self) -> None:
        """HTML exceeding _MAX_HTML_SIZE (5MB) must return [] (DoS protection).

        Constructs a 5MB+10 HTML string; parser must reject without parsing.
        """
        from modules.search.web.html_parser import _MAX_HTML_SIZE

        # Build HTML just over the size cap. Fill with comment padding to
        # avoid creating millions of b_algo nodes (which would be slow).
        skeleton = '<html><body><li class="b_algo"><h2><a href="https://x.com">T</a></h2></li>'
        # Target total length = _MAX_HTML_SIZE + 10 (strictly greater than cap).
        target_total = _MAX_HTML_SIZE + 10
        # padding = "<!-- " + "x" * N + " -->" has overhead 5 + 4 = 9 chars.
        padding_inner = max(target_total - len(skeleton) - 9, 0)
        padding = "<!-- " + "x" * padding_inner + " -->"
        oversized_html = skeleton + padding
        assert len(oversized_html) == target_total
        assert len(oversized_html) > _MAX_HTML_SIZE
        results = parse_bing_html(oversized_html)
        assert results == []

    def test_parse_accepts_html_at_size_boundary(self) -> None:
        """HTML just under _MAX_HTML_SIZE must parse normally."""
        from modules.search.web.html_parser import _MAX_HTML_SIZE

        # Build HTML just under the cap with one valid result.
        skeleton = '<html><body><li class="b_algo"><h2><a href="https://x.com">T</a></h2></li>'
        # Target total length = _MAX_HTML_SIZE (exactly at cap; parser uses
        # strict > so equal-length HTML is still accepted).
        target_total = _MAX_HTML_SIZE
        padding_inner = max(target_total - len(skeleton) - 9, 0)
        padding = "<!-- " + "x" * padding_inner + " -->"
        boundary_html = skeleton + padding
        assert len(boundary_html) == target_total
        assert len(boundary_html) <= _MAX_HTML_SIZE
        results = parse_bing_html(boundary_html)
        assert len(results) == 1
        assert results[0].title == "T"


class TestParseBingNewsHtmlBasic:
    """Tests for parse_bing_news_html (R-web-search-008 news vertical).

    Validates parsing of ``cn.bing.com/news/search`` HTML structure, which
    differs from general search: items live in ``div.newsitem`` with
    ``a.title`` (href) and ``div.snippet``.
    """

    def test_parse_news_returns_list_of_bing_search_result(self) -> None:
        """Return value must be list[BingSearchResult]."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, BingSearchResult)

    def test_parse_news_extracts_newsitem_cards(self) -> None:
        """News cards (div.newsitem > a.title) must be extracted.

        Fixture has 3 valid newsitem cards (4th/5th missing href/title).
        Plus one mixed-in li.b_algo. Total = 4.
        """
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html)
        assert len(results) == 4

    def test_parse_news_extracts_title_url_snippet_correctly(self) -> None:
        """First news entry must have correct title/url/snippet from fixture."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html)
        first = results[0]
        assert "仁爱礁" in first.title
        assert first.url == "https://news.example.com/renai-reef-1"
        assert "仁爱礁" in first.snippet

    def test_parse_news_preserves_document_order(self) -> None:
        """News items must be returned in document order (news first, then mixed)."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html)
        titles = [r.title for r in results]
        # First 3 are newsitem cards, 4th is the mixed-in b_algo
        assert "仁爱礁" in titles[0]
        assert "外交部" in titles[1]
        assert "南海局势" in titles[2]
        assert "专题报道" in titles[3]

    def test_parse_news_strips_whitespace(self) -> None:
        """Title and snippet whitespace must be stripped."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html)
        # Third news card has whitespace-padded title/snippet
        third = results[2]
        assert third.title == "南海局势：仁爱礁争端的来龙去脉"
        assert third.snippet == "解析仁爱礁争端的历史背景与菲律宾方面的诉求。"


class TestParseBingNewsHtmlEdgeCases:
    """Edge cases for parse_bing_news_html."""

    def test_parse_news_empty_html_returns_empty_list(self) -> None:
        """Empty string HTML must return [] (not raise)."""
        from modules.search.web.html_parser import parse_bing_news_html

        assert parse_bing_news_html("") == []

    def test_parse_news_none_input_returns_empty_list(self) -> None:
        """None input must return [] (defensive)."""
        from modules.search.web.html_parser import parse_bing_news_html

        assert parse_bing_news_html(None) == []  # type: ignore[arg-type]

    def test_parse_news_html_without_newsitem_returns_empty_list(self) -> None:
        """HTML lacking div.newsitem and li.b_algo must return []."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = "<html><body><p>no news here</p></body></html>"
        assert parse_bing_news_html(html) == []

    def test_parse_news_skips_results_without_href(self) -> None:
        """newsitem entries with <a> but no href must be skipped."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title">Title without href</a>
          <div class="snippet">snippet</div>
        </div>
        """
        results = parse_bing_news_html(html)
        assert results == []

    def test_parse_news_skips_results_without_title_text(self) -> None:
        """newsitem entries with empty <a> text must be skipped."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title" href="https://example.com"></a>
          <div class="snippet">snippet</div>
        </div>
        """
        results = parse_bing_news_html(html)
        assert results == []

    def test_parse_news_handles_missing_snippet_gracefully(self) -> None:
        """newsitem without div.snippet must still yield result with empty snippet."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title" href="https://example.com">Title Without Snippet</a>
        </div>
        """
        results = parse_bing_news_html(html)
        assert len(results) == 1
        assert results[0].title == "Title Without Snippet"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == ""

    def test_parse_news_deduplicates_by_url(self) -> None:
        """Same URL appearing in both newsitem and b_algo must be returned once."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title" href="https://example.com/dup">Dup Title News</a>
          <div class="snippet">news snippet</div>
        </div>
        <li class="b_algo">
          <h2><a href="https://example.com/dup">Dup Title General</a></h2>
          <div class="b_caption"><p>general snippet</p></div>
        </li>
        """
        results = parse_bing_news_html(html)
        # Deduplicated by URL — first occurrence (newsitem) wins.
        assert len(results) == 1
        assert results[0].title == "Dup Title News"
        assert results[0].snippet == "news snippet"


class TestParseBingNewsHtmlMaxResults:
    """max_results truncation for parse_bing_news_html."""

    def test_parse_news_respects_max_results_argument(self) -> None:
        """max_results must cap the returned count (news items first)."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        # Fixture has 3 news items + 1 mixed b_algo = 4 total; cap at 2
        results = parse_bing_news_html(html, max_results=2)
        assert len(results) == 2
        # First 2 must be news items (news selector runs before b_algo)
        assert "仁爱礁" in results[0].title
        assert "外交部" in results[1].title

    def test_parse_news_max_results_zero_returns_empty_list(self) -> None:
        """max_results=0 must return empty list."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        assert parse_bing_news_html(html, max_results=0) == []

    def test_parse_news_max_results_negative_returns_empty_list(self) -> None:
        """Negative max_results must return empty list (defensive)."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        assert parse_bing_news_html(html, max_results=-1) == []

    def test_parse_news_max_results_larger_than_actual_returns_all(self) -> None:
        """max_results larger than result count returns all (4) results."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = _load_fixture("bing_news_sample.html")
        results = parse_bing_news_html(html, max_results=100)
        assert len(results) == 4


class TestParseBingNewsHtmlSecurity:
    """Security hardening for parse_bing_news_html (mirrors general parser)."""

    def test_parse_news_rejects_javascript_scheme_url(self) -> None:
        """javascript: scheme URLs must be skipped (XSS prevention)."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title" href="javascript:alert('xss')">XSS Title</a>
          <div class="snippet">snippet</div>
        </div>
        <div class="newsitem">
          <a class="title" href="https://example.com/safe">Safe Title</a>
          <div class="snippet">safe snippet</div>
        </div>
        """
        results = parse_bing_news_html(html)
        assert len(results) == 1
        assert results[0].title == "Safe Title"
        assert results[0].url == "https://example.com/safe"

    def test_parse_news_rejects_data_scheme_url(self) -> None:
        """data: scheme URLs must be skipped (XSS / payload injection)."""
        from modules.search.web.html_parser import parse_bing_news_html

        html = """
        <div class="newsitem">
          <a class="title" href="data:text/html,<script>alert(1)</script>">Data URL</a>
        </div>
        """
        results = parse_bing_news_html(html)
        assert results == []

    def test_parse_news_rejects_oversized_html(self) -> None:
        """HTML exceeding _MAX_HTML_SIZE must return [] (DoS protection)."""
        from modules.search.web.html_parser import _MAX_HTML_SIZE, parse_bing_news_html

        skeleton = (
            '<html><body><div class="newsitem"><a class="title" href="https://x.com">T</a></div>'
        )
        target_total = _MAX_HTML_SIZE + 10
        padding_inner = max(target_total - len(skeleton) - 9, 0)
        padding = "<!-- " + "x" * padding_inner + " -->"
        oversized_html = skeleton + padding
        assert len(oversized_html) == target_total
        assert len(oversized_html) > _MAX_HTML_SIZE
        results = parse_bing_news_html(oversized_html)
        assert results == []
