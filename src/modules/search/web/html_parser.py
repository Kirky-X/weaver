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
        if not title or not url:
            continue

        # URL scheme whitelist: reject javascript:/data:/file:/blob:/etc.
        # urlparse handles leading whitespace and control chars by stripping
        # them before scheme extraction.
        parsed_scheme = urlparse(url).scheme.lower()
        if parsed_scheme not in _ALLOWED_URL_SCHEMES:
            continue

        snippet_node = li.select_one(".b_caption p")
        snippet = snippet_node.get_text(strip=True) if snippet_node else ""

        results.append(BingSearchResult(title=title, url=url, snippet=snippet))

        # Early exit if we've collected enough results.
        if max_results is not None and len(results) >= max_results:
            break

    return results
