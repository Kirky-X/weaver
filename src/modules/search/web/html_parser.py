# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Bing search result HTML parser.

Parses the HTML response from ``https://cn.bing.com/search?q=...`` and
extracts a list of ``BingSearchResult`` objects.

Strategy:
    - Use BeautifulSoup4 with the stdlib ``html.parser`` backend (no extra
      native deps required). BeautifulSoup4 is declared explicitly in
      pyproject.toml as a direct dependency (not transitively guaranteed
      by trafilatura — its dependency list may change across versions).
    - Bing result items live in ``li.b_algo`` nodes.
    - Title + URL come from ``h2 a`` (text + href).
    - Snippet comes from ``.b_caption p`` (text). Missing snippet yields
      an empty string (not a skip).

Defensive behavior:
    - ``None`` / empty / non-string HTML → ``[]``
    - HTML exceeding ``_MAX_HTML_SIZE`` → ``[]`` (DoS protection)
    - Malformed HTML (parse errors) → ``[]``
    - ``li.b_algo`` without ``h2 a`` href or title text → skipped
    - URL with non-http(s) scheme (javascript:/data:/file:) → skipped
    - ``max_results`` ≤ 0 → ``[]``; ``max_results=None`` → all valid results

R-web-search-008 — News vertical parser:
    ``parse_bing_news_html`` parses ``cn.bing.com/news/search`` responses.
    Bing News uses different DOM structure than general search: items live
    in ``div.newsitem`` (inside ``div.news_card``), with title/url in
    ``a.title`` and snippet in ``div.snippet``. A ``parse_bing_html`` fallback
    catches any mixed-in ``li.b_algo`` cards (Bing News occasionally
    interleaves general-result cards).
"""

from __future__ import annotations

from urllib.parse import urlparse

from modules.search.web.protocol import BingSearchResult

# DoS protection: cap HTML size at 5MB. Typical Bing result page is ~100KB;
# anything larger is either malicious or a streaming glitch.
_MAX_HTML_SIZE = 5_000_000

# URL scheme whitelist. Bing result <a href> values should always be
# http/https; rejecting javascript:/data:/vbscript:/file:/blob: prevents
# downstream consumers from inadvertently triggering XSS or local-file
# access when rendering or fetching result.url.
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _is_safe_url(url: str) -> bool:
    """Return True iff ``url`` has an http(s) scheme (XSS/local-file defense)."""
    if not url:
        return False
    parsed_scheme = urlparse(url).scheme.lower()
    return parsed_scheme in _ALLOWED_URL_SCHEMES


def parse_bing_html(
    html: str | None,
    max_results: int | None = None,
) -> list[BingSearchResult]:
    """Parse Bing search result HTML and extract result entries.

    Args:
        html: Raw HTML string from cn.bing.com/search. ``None`` or empty
            string yields an empty list (no exception).
        max_results: Optional upper bound on returned results.
            - ``None`` (default): return all valid results.
            - ``0`` or negative: return empty list.
            - Positive ``N``: return at most ``N`` results (in document order).

    Returns:
        List of ``BingSearchResult`` in document order. Entries missing
        title or URL are skipped. Entries with non-http(s) URL scheme are
        skipped. Entries missing snippet get an empty string.
    """
    # Defensive: None / empty input → empty list.
    if not html or not isinstance(html, str):
        return []

    # DoS protection: reject oversized HTML before parsing.
    if len(html) > _MAX_HTML_SIZE:
        return []

    # max_results defensive: non-positive → empty list.
    if max_results is not None and max_results <= 0:
        return []

    # Lazy import: bs4 first-time load is ~50-100ms; defer until first call
    # so server startup doesn't pay for a fallback path that may never run.
    # Subsequent calls hit sys.modules cache.
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # beautifulsoup4 should be in dependencies; if missing, degrade
        # gracefully rather than crash the search fallback path.
        return []

    # Parse HTML. BeautifulSoup with html.parser handles malformed input
    # gracefully (returns partial tree) without raising.
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        # Highly unlikely with html.parser, but defensive.
        return []

    results: list[BingSearchResult] = []
    for li in soup.select("li.b_algo"):
        title_link = li.select_one("h2 a")
        if title_link is None:
            continue

        title = title_link.get_text(strip=True)
        url = title_link.get("href", "") or ""

        # Skip entries without title text or URL — they're not useful results.
        if not title or not _is_safe_url(url):
            continue

        snippet_node = li.select_one(".b_caption p")
        snippet = snippet_node.get_text(strip=True) if snippet_node else ""

        results.append(BingSearchResult(title=title, url=url, snippet=snippet))

        # Early exit if we've collected enough results.
        if max_results is not None and len(results) >= max_results:
            break

    return results


def parse_bing_news_html(
    html: str | None,
    max_results: int | None = None,
) -> list[BingSearchResult]:
    """Parse Bing News search result HTML and extract news entries.

    Mirrors ``parse_bing_html`` but for the news vertical
    (``cn.bing.com/news/search``). Bing News uses a different DOM:
    items live in ``div.newsitem`` (typically wrapped in
    ``div.news_card``), title+url come from ``a.title``, and snippet from
    ``div.snippet``.

    The parser also falls back to ``li.b_algo`` parsing because Bing News
    occasionally interleaves general-result cards (mixed feed); the union
    is deduplicated by URL so a card appearing in both selectors is
    returned only once.

    Args:
        html: Raw HTML string from cn.bing.com/news/search. ``None`` or
            empty string yields an empty list (no exception).
        max_results: Optional upper bound on returned results.
            - ``None`` (default): return all valid results.
            - ``0`` or negative: return empty list.
            - Positive ``N``: return at most ``N`` results (news items first,
              then any mixed-in general cards, in document order).

    Returns:
        List of ``BingSearchResult`` in document order. Entries missing
        title or URL are skipped. Entries with non-http(s) URL scheme are
        skipped. Entries missing snippet get an empty string. Duplicates
        (by URL) are removed — the first occurrence wins.
    """
    if not html or not isinstance(html, str):
        return []

    if len(html) > _MAX_HTML_SIZE:
        return []

    if max_results is not None and max_results <= 0:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    results: list[BingSearchResult] = []
    seen_urls: set[str] = set()

    # 1) News cards: div.newsitem > a.title (href) + div.snippet
    for item in soup.select("div.newsitem"):
        title_link = item.select_one("a.title")
        if title_link is None:
            continue

        title = title_link.get_text(strip=True)
        url = title_link.get("href", "") or ""

        if not title or not _is_safe_url(url):
            continue

        # Deduplicate by URL — Bing News sometimes repeats the same article
        # in different card layouts on the same page.
        if url in seen_urls:
            continue
        seen_urls.add(url)

        snippet_node = item.select_one("div.snippet")
        snippet = snippet_node.get_text(strip=True) if snippet_node else ""

        results.append(BingSearchResult(title=title, url=url, snippet=snippet))

        if max_results is not None and len(results) >= max_results:
            return results

    # 2) Fallback: also pick up any li.b_algo cards that Bing News
    # occasionally mixes in. Deduplicated against the news set by URL.
    for li in soup.select("li.b_algo"):
        title_link = li.select_one("h2 a")
        if title_link is None:
            continue

        title = title_link.get_text(strip=True)
        url = title_link.get("href", "") or ""

        if not title or not _is_safe_url(url):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        snippet_node = li.select_one(".b_caption p")
        snippet = snippet_node.get_text(strip=True) if snippet_node else ""

        results.append(BingSearchResult(title=title, url=url, snippet=snippet))

        if max_results is not None and len(results) >= max_results:
            break

    return results
