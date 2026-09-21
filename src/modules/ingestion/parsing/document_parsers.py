# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Parsers for non-feed source types: HTML index pages, JSON APIs, PDF documents.

These parsers exist so that ``SourceType.HTML`` / ``SourceType.JSON`` /
``SourceType.PDF`` actually resolve to a parser. Previously these types were
declared in ``core.constants.SourceType`` and accepted by the create-source
API, but ``SourceRegistry`` only registered ``rss`` / ``newsnow`` — so any such
source hit ``no_parser_for_type`` in ``SourceScheduler._crawl_source`` and was
silently never crawled (created successfully, zero output, no error).

Each parser is intentionally conservative: it returns ``[]`` (a clean no-op)
instead of raising when content cannot be understood, mirroring ``RSSParser``
and ``NewsNowParser``. A source that yields nothing is treated as "no new
items" by the scheduler and does not count toward auto-disable.
"""

from __future__ import annotations

import asyncio
import html
import io
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from core.observability import get_logger
from modules.ingestion.domain.models import NewsItem, SourceConfig
from modules.ingestion.parsing.base import BaseSourceParser

if TYPE_CHECKING:
    from modules.ingestion.fetching.base import BaseFetcher

log = get_logger(__name__)

# Minimum number of characters for extracted text to be considered real content.
MIN_EXTRACTED_LENGTH = 100

# Safety cap on how many items a single HTML index page may yield, so a
# misconfigured URL (e.g. a site's full sitemap) cannot flood the pipeline.
MAX_ITEMS_PER_INDEX = 200

# Index pages link to far more than articles: social profiles, terms pages,
# and — noisiest of all — section indexes (/business/banking). Section and
# service links fetch fine but carry no article, so link extraction keeps
# only same-host paths in article shape. The shape is derived from the four
# built-in English sites (BBC/CNN/Guardian/Times): real articles are ≥3 path
# segments with a substantial terminal slug (/news/articles/c0000000000,
# /2026/09/21/economy/slug, /business/2026/sep/21/slug,
# /business/companies-markets/article/slug-1a2b3c4); sections and service
# pages are 1-2 segments. The live suite (test_index_sources_live.py) fails
# loudly if a future source's article shape violates this.
MIN_PATH_SEGMENTS = 3
MIN_SLUG_LENGTH = 8
# Aggregation hubs that live *inside* long paths (/future/tags/x,
# /news/video/y) are not articles either.
NAV_SEGMENTS = frozenset(
    {
        "tag",
        "tags",
        "topics",
        "topic",
        "category",
        "categories",
        "video",
        "videos",
        "audio",
        "podcast",
        "podcasts",
        "live",
        "gallery",
        "galleries",
    }
)


def _looks_like_json(text: str) -> bool:
    """Cheap pre-check before handing a payload to json_repair."""
    stripped = text.lstrip()
    return stripped.startswith(("{", "["))


# Only tags (name right after ``<``) are stripped, so titles containing
# comparisons like "增速 < 5% 的行业 > 预期" survive untouched.
_MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>")

# Cap for a single item title: legacy JSON APIs can carry multi-KB strings.
MAX_TITLE_LENGTH = 2048

# SmartFetcher's crawl4ai fallback renders JSON endpoints through a browser,
# which wraps the payload in a document (``<html><body><pre>[...]</pre>…``).
# Extracted with a forward-only find chain instead of a regex: a regex over
# attacker-controlled HTML can backtrack quadratically, and this runs per
# crawl on arbitrarily large responses.
_MAX_BROWSER_WRAP_SCAN = 256 * 1024


def _extract_json_payload(content: str) -> str:
    """Return the JSON payload from ``content``, unwrapping browser HTML.

    Bare JSON passes through untouched; an HTML document contributes the body
    of its first ``<pre>`` block (entities unescaped — URLs in the payload
    carry ``&amp;`` after rendering). Content with neither shape is returned
    as-is so the caller's JSON pre-check rejects it.
    """
    if _looks_like_json(content):
        return content
    lower = content.lower()[:_MAX_BROWSER_WRAP_SCAN]
    start = lower.find("<pre")
    if start == -1:
        return content
    open_end = lower.find(">", start)
    if open_end == -1:
        return content
    body_start = open_end + 1
    end = lower.find("</pre", body_start)
    body = content[body_start:] if end == -1 else content[body_start:end]
    return html.unescape(body)


def _normalize_host(netloc: str) -> str:
    """Lowercase a host and drop its ``www.`` prefix for same-site checks."""
    host = (netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


class HTMLIndexParser(BaseSourceParser):
    """Parses an HTML page for links to individual articles.

    Handles the "section/index page" source shape: an HTML listing (news
    homepage, category page, sitemap) whose anchors point at the articles we
    actually want. Link extraction is intentionally generic — the discovered
    URLs are handed to ``Crawler``, which extracts the real article body via
    trafilatura later in the pipeline.

    Args:
        fetcher: BaseFetcher instance for page fetching.
    """

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, config: SourceConfig, force: bool = False) -> list[NewsItem]:
        """Fetch an HTML index page and return the article links it contains.

        Args:
            config: Source configuration with the index page URL.
            force: Unused — HTML index pages carry no incremental state.

        Returns:
            List of NewsItem for discovered links (bodies unfetched).
        """
        try:
            status_code, content, _ = await self._fetcher.fetch(config.url)
        except Exception as exc:
            log.warning("html_index_fetch_failed", url=config.url, error=str(exc))
            return []

        if status_code != 200:
            log.warning("html_index_unexpected_status", url=config.url, status=status_code)
            return []

        if not content:
            log.warning("html_index_empty_content", url=config.url)
            return []

        # trafilatura link extraction is CPU-bound; keep it off the event loop.
        urls = await asyncio.to_thread(self._extract_links, content, config.url)

        items: list[NewsItem] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            items.append(
                NewsItem(
                    url=url,
                    title=self._title_from_url(url),
                    source=config.name,
                    source_host=urlparse(url).netloc,
                    source_id=config.id,
                    description="",
                )
            )
            if len(items) >= MAX_ITEMS_PER_INDEX:
                log.debug("html_index_item_cap_reached", url=config.url, cap=MAX_ITEMS_PER_INDEX)
                break

        log.info("html_index_parsed", url=config.url, items_found=len(items))
        return items

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract absolute http(s) article links from an HTML page.

        Uses trafilatura's link extraction when it yields anything, and falls
        back to a regex anchor scan so a page trafilatura cannot parse (e.g. an
        XML sitemap) still produces results. Candidates are then filtered to
        same-host links in article shape (see the MIN_PATH_SEGMENTS block) —
        index pages link to sections, terms pages and social profiles just as
        liberally as to articles, and every kept link costs a fetch.

        Args:
            html: Raw HTML/XML content.
            base_url: URL used to resolve relative links and define "same host".

        Returns:
            List of absolute http(s) URLs, in document order.
        """
        import trafilatura

        candidates: list[str] = []
        try:
            extracted = trafilatura.extract_links(html, base_url)
            candidates.extend(str(link) for link in extracted)
        except Exception as exc:
            log.debug("html_index_trafilatura_links_failed", url=base_url, error=str(exc))

        if not candidates:
            candidates.extend(match.group(1) for match in _ANCHOR_RE.finditer(html))

        base_host = _normalize_host(urlparse(base_url).netloc)
        resolved: list[str] = []
        for candidate in candidates:
            absolute = urljoin(base_url, candidate.strip())
            if not absolute.startswith(("http://", "https://")):
                continue
            if not HTMLIndexParser._is_article_link(absolute, base_host):
                continue
            resolved.append(absolute)

        dropped = len(candidates) - len(resolved)
        if dropped:
            log.info("html_index_links_filtered", url=base_url, dropped=dropped, kept=len(resolved))
        return resolved

    @staticmethod
    def _is_article_link(url: str, base_host: str) -> bool:
        """Whether ``url`` looks like an article on ``base_host``.

        Same host (``www.`` normalized), at least ``MIN_PATH_SEGMENTS`` path
        segments, no nav segment anywhere in the path, and a terminal slug of
        at least ``MIN_SLUG_LENGTH`` characters.
        """
        parsed = urlparse(url)
        if _normalize_host(parsed.netloc) != base_host:
            return False
        segments = [seg for seg in parsed.path.split("/") if seg]
        if len(segments) < MIN_PATH_SEGMENTS:
            return False
        if any(seg.lower() in NAV_SEGMENTS for seg in segments):
            return False
        terminal = segments[-1]
        # Strip a file extension so "story.html" is judged on "story".
        terminal = re.sub(r"\.[a-zA-Z0-9]{1,5}$", "", terminal)
        return len(terminal) >= MIN_SLUG_LENGTH

    @staticmethod
    def _title_from_url(url: str) -> str:
        """Derive a placeholder title from a URL's last path segment.

        Titles are best-effort here: ``Crawler`` re-extracts a real title from
        the article HTML when the item carries none, and the title-dedup
        stages downstream match on the final crawled title.
        """
        path = urlparse(url).path.rstrip("/")
        slug = path.rsplit("/", 1)[-1] if path else ""
        slug = re.sub(r"\.(html?|php|aspx?|jsp)$", "", slug, flags=re.IGNORECASE)
        return re.sub(r"[-_]+", " ", slug).strip()


class JSONApiParser(BaseSourceParser):
    """Parses a JSON list endpoint into NewsItems.

    Accepts the common shapes without requiring per-site configuration:

    - a bare list of objects: ``[{...}, {...}]``
    - an object wrapping the list under a well-known key
      (``items`` / ``data`` / ``list`` / ``results`` / ``articles`` / ``entries``
      / ``datasource``)

    Each object is expected to expose a URL under one of
    ``url`` / ``link`` / ``href`` / ``publishUrl`` (plus
    ``title`` / ``name`` / ``headline``). Key lookup falls back to a
    case-insensitive match so legacy list APIs that use UPPERCASE field names
    (``URL`` / ``TITLE`` / ``DOCRELPUBTIME``) resolve without per-site config.
    Titles are stripped of inline markup (``<a href=...>标题</a>`` wrappers).
    Objects that do not yield a usable URL are skipped rather than failing the
    whole batch.

    Args:
        fetcher: BaseFetcher instance for API fetching.
    """

    URL_KEYS = ("url", "link", "href", "publishUrl")
    TITLE_KEYS = ("title", "name", "headline")
    DATE_KEYS = (
        "date",
        "published",
        "published_at",
        "pubDate",
        "timestamp",
        "created_at",
        "publishTime",
        "docRelPubTime",
    )
    LIST_KEYS = ("items", "data", "list", "results", "articles", "entries", "datasource")

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, config: SourceConfig, force: bool = False) -> list[NewsItem]:
        """Fetch a JSON endpoint and return the items it describes.

        Args:
            config: Source configuration with the JSON endpoint URL.
            force: Unused — JSON API sources carry no incremental state.

        Returns:
            List of NewsItem for discovered entries.
        """
        try:
            status_code, content, _ = await self._fetcher.fetch(config.url)
        except Exception as exc:
            log.warning("json_api_fetch_failed", url=config.url, error=str(exc))
            return []

        if status_code != 200:
            log.warning("json_api_unexpected_status", url=config.url, status=status_code)
            return []

        if not content:
            log.warning("json_api_not_json", url=config.url)
            return []

        # Payload extraction and JSON decode are CPU-bound on multi-MB
        # responses; keep them off the event loop like HTMLIndexParser does.
        try:
            payload, data = await asyncio.to_thread(JSONApiParser._decode_payload, content)
        except Exception as exc:
            log.warning("json_api_parse_failed", url=config.url, error=str(exc))
            return []

        if not payload:
            log.warning("json_api_not_json", url=config.url)
            return []

        entries = self._unwrap(data)
        if entries is None:
            log.warning(
                "json_api_unrecognized_shape",
                url=config.url,
                payload_type=type(data).__name__,
            )
            return []

        items: list[NewsItem] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = self._first_str(entry, self.URL_KEYS)
            if not url:
                continue
            absolute = urljoin(config.url, url)
            if not absolute.startswith(("http://", "https://")):
                continue

            items.append(
                NewsItem(
                    url=absolute,
                    title=self._strip_markup(self._first_str(entry, self.TITLE_KEYS) or ""),
                    source=config.name,
                    source_host=urlparse(absolute).netloc,
                    source_id=config.id,
                    publish_time=self._parse_date(entry),
                    description="",
                )
            )
            if len(items) >= MAX_ITEMS_PER_INDEX:
                log.debug("json_api_item_cap_reached", url=config.url, cap=MAX_ITEMS_PER_INDEX)
                break

        log.info("json_api_parsed", url=config.url, items_found=len(items))
        return items

    @staticmethod
    def _decode_payload(content: str) -> tuple[str, object]:
        """Extract the JSON payload from ``content`` and decode it.

        Runs in a worker thread (see ``parse``). Returns an empty payload
        when ``content`` carries no recognizable JSON so the caller logs the
        not-json outcome; raises when the decode itself fails.
        """
        import json_repair

        payload = _extract_json_payload(content)
        if not _looks_like_json(payload):
            return "", None
        return payload, json_repair.loads(payload)

    @classmethod
    def _unwrap(cls, data: object) -> list | None:
        """Locate the entry list inside a decoded JSON payload.

        Args:
            data: Decoded JSON value.

        Returns:
            The list of entries, or None when the shape is not recognized.
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in cls.LIST_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return None

    @staticmethod
    def _get_field(entry: dict, key: str) -> object | None:
        """Fetch ``key`` from ``entry``, falling back to a case-insensitive match.

        A hit whose value is None/empty is treated as a miss so mixed-case
        legacy entries (``{"url": "", "URL": "https://..."}``) still resolve;
        exact hits with real values keep precedence over the fallback.
        """
        value = entry.get(key)
        if value not in (None, ""):
            return value
        key_lower = key.lower()
        for entry_key, entry_value in entry.items():
            # Skip the exact key itself: its None/empty value is why we are
            # here, and re-matching it would return the same empty value.
            if isinstance(entry_key, str) and entry_key != key and entry_key.lower() == key_lower:
                return entry_value
        return None

    @classmethod
    def _first_str(cls, entry: dict, keys: tuple[str, ...]) -> str | None:
        """Return the first non-empty string value among ``keys``."""
        for key in keys:
            value = cls._get_field(entry, key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove inline HTML tags and collapse surrounding whitespace."""
        return _MARKUP_RE.sub("", text).strip()[:MAX_TITLE_LENGTH]

    @classmethod
    def _parse_date(cls, entry: dict) -> datetime | None:
        """Best-effort publication-date extraction from a JSON entry.

        Accepts ISO 8601 strings and epoch seconds/milliseconds. Returns None
        when nothing parseable is found — callers treat a missing date as
        "always include".
        """
        for key in cls.DATE_KEYS:
            raw = cls._get_field(entry, key)
            if raw is None:
                continue

            if isinstance(raw, (int, float)):
                ts = float(raw)
                # Heuristic: values above this are milliseconds, not seconds.
                if ts > 1e11:
                    ts /= 1000.0
                try:
                    return datetime.fromtimestamp(ts, tz=UTC)
                except (OverflowError, OSError, ValueError):
                    continue

            if isinstance(raw, str) and raw.strip():
                text = raw.strip().replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(text)
                except ValueError:
                    continue
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None


class PDFDocumentParser(BaseSourceParser):
    """Parses a source URL that points directly at a PDF document.

    The document is emitted as a single NewsItem whose ``body`` carries the
    extracted text, so ``Crawler`` can skip the network round-trip (it reuses
    a pre-filled body when it is long enough).

    Text extraction prefers pypdf, then pdfplumber.

    The document is fetched via ``fetch_bytes`` when the fetcher provides it,
    so the raw PDF is never put through text decoding (which would corrupt
    non-UTF-8 bytes). Fetchers without that method fall back to re-encoding
    the decoded text, which is lossy for anything but single-byte charsets —
    such payloads fail extraction and yield an empty list rather than a
    corrupt body.

    Args:
        fetcher: BaseFetcher instance for document fetching.
    """

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, config: SourceConfig, force: bool = False) -> list[NewsItem]:
        """Fetch a PDF and return it as a single NewsItem.

        Prefers the byte-exact ``fetch_bytes`` path so the PDF is never
        mangled by text decoding; falls back to ``fetch`` for fetchers that
        do not expose it.

        Args:
            config: Source configuration with the PDF URL.
            force: Unused — a PDF is a single immutable document.

        Returns:
            A one-element list on success, or an empty list when the document
            could not be fetched or its text could not be extracted.
        """
        raw = await self._fetch_pdf_bytes(config.url)
        if raw is None:
            return []

        text = await asyncio.to_thread(self._extract_text_safe, raw)
        if not text:
            log.warning("pdf_text_extraction_failed", url=config.url)
            return []

        name = urlparse(config.url).path.rstrip("/").rsplit("/", 1)[-1]
        title = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE) or config.name

        log.info("pdf_parsed", url=config.url, text_len=len(text))
        return [
            NewsItem(
                url=config.url,
                title=title,
                source=config.name,
                source_host=urlparse(config.url).netloc,
                source_id=config.id,
                description="",
                body=text,
            )
        ]

    async def _fetch_pdf_bytes(self, url: str) -> bytes | None:
        """Fetch the PDF body as raw bytes.

        Args:
            url: The PDF URL.

        Returns:
            The raw body, or None when the fetch failed or returned non-200.
        """
        try:
            if hasattr(self._fetcher, "fetch_bytes"):
                status_code, content, _ = await self._fetcher.fetch_bytes(url)
            else:
                # Fetcher without a byte-exact path: re-encode the decoded
                # text. Correct for single-byte payloads, lossy otherwise.
                status_code, text, _ = await self._fetcher.fetch(url)
                content = text.encode("latin-1", errors="ignore")
        except Exception as exc:
            log.warning("pdf_fetch_failed", url=url, error=str(exc))
            return None

        if status_code != 200:
            log.warning("pdf_unexpected_status", url=url, status=status_code)
            return None

        if not content:
            log.warning("pdf_empty_content", url=url)
            return None

        return content

    @staticmethod
    def _extract_text_safe(raw: bytes) -> str:
        """``_extract_text`` wrapper that never raises.

        ``_extract_text`` raises ValueError on a non-PDF signature, which is
        the expected outcome when a PDF source URL actually serves HTML (a
        redirect to a login page, an expired link). Convert that into an empty
        result so the parser degrades to a clean no-op like the other parsers
        instead of failing the whole crawl batch.

        Args:
            raw: PDF payload bytes.

        Returns:
            Extracted text, or "" when extraction was not possible.
        """
        try:
            return PDFDocumentParser._extract_text(raw)
        except ValueError as exc:
            log.debug("pdf_not_a_pdf_payload", error=str(exc))
            return ""
        except Exception as exc:
            log.warning("pdf_unexpected_extraction_error", error=str(exc))
            return ""

    @staticmethod
    def _extract_text(raw: bytes) -> str:
        """Extract plain text from PDF bytes.

        Args:
            raw: PDF payload bytes.

        Returns:
            Extracted text, or an empty string when no extractor succeeded or
            the extracted text is too short to be real content.

        Raises:
            ValueError: If ``raw`` has no PDF signature.
        """
        if not raw.startswith(b"%PDF"):
            raise ValueError("content does not start with a PDF signature")

        text = PDFDocumentParser._extract_with_pypdf(raw)
        if not text:
            text = PDFDocumentParser._extract_with_pdfplumber(raw)

        normalized = re.sub(r"[ \t]+", " ", text).strip()
        return normalized if len(normalized) >= MIN_EXTRACTED_LENGTH else ""

    @staticmethod
    def _extract_with_pypdf(raw: bytes) -> str:
        """Try text extraction with pypdf. Returns "" when unavailable."""
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        try:
            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip()
        except Exception as exc:
            log.debug("pdf_pypdf_extraction_failed", error=str(exc))
            return ""

    @staticmethod
    def _extract_with_pdfplumber(raw: bytes) -> str:
        """Try text extraction with pdfplumber. Returns "" when unavailable."""
        try:
            import pdfplumber
        except ImportError:
            return ""
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages).strip()
        except Exception as exc:
            log.debug("pdf_pdfplumber_extraction_failed", error=str(exc))
            return ""


# Anchors for the regex fallback in HTMLIndexParser._extract_links.
_ANCHOR_RE = re.compile(r'<a\s[^>]*href=["\']([^"\'>]+)["\']', re.IGNORECASE)
