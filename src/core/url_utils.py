# Copyright (c) 2026 KirkyX. All Rights Reserved
"""URL normalization utilities.

Extracted from Deduplicator.normalize_url to break circular dependency
between storage and ingestion modules.
"""

from __future__ import annotations

import posixpath
from urllib.parse import quote, unquote, urlparse, urlunparse

from core.observability import get_logger

log = get_logger(__name__)


def normalize_url(url: str) -> str:
    """Normalize a URL for consistent deduplication using urllib.parse.

    Normalization rules:
    1. Protocol-relative URLs → HTTPS (//example.com → https://example.com)
    2. HTTP → HTTPS upgrade
    3. Domain lowercase
    4. Remove www. prefix
    5. Remove default ports (80 for HTTP, 443 for HTTPS)
    6. Decode percent-encoded characters, then re-encode consistently
    7. Normalize path (resolve . and ..)
    8. ~~Remove query string~~ (removed — query params often carry article IDs)
    9. Remove fragment
    10. Remove trailing slash (except for root which becomes no slash)

    Args:
        url: The URL to normalize.

    Returns:
        Normalized URL string.
    """
    # Handle protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url

    # Parse the URL
    parsed = urlparse(url)

    # 1. Normalize scheme: HTTP → HTTPS
    scheme = parsed.scheme.lower()
    original_scheme = scheme
    if scheme == "http":
        scheme = "https"

    # 2. Normalize netloc: lowercase, remove www., remove default ports
    netloc = parsed.netloc.lower()

    # Remove www. prefix
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove default ports based on ORIGINAL scheme before upgrade
    # For HTTP URLs (upgraded to HTTPS), port 80 should be removed
    # For HTTPS URLs, port 443 should be removed
    if original_scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]

    # 3. Normalize path
    path = parsed.path

    # Decode percent-encoded characters
    path = unquote(path)

    # Normalize path (resolve . and ..)
    path = posixpath.normpath(path)

    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path

    # Remove trailing slash (including root path)
    if path.endswith("/"):
        path = path.rstrip("/")

    # Re-encode path (preserve non-ASCII characters for readability)
    path = quote(path, safe="/", encoding="utf-8")

    # Handle empty path
    if not path:
        path = ""

    # 4. Remove query string and fragment
    # Special case: Some sites use query params as article identifiers:
    # - WeChat: __biz + mid + idx
    # - Solidot: sid
    # Preserve these to avoid collapsing distinct articles into one.
    if netloc in ("mp.weixin.qq.com", "solidot.org", "www.solidot.org"):
        query_params = parsed.query.split("&") if parsed.query else []
        kept = []
        dropped = []
        for param in query_params:
            if param.startswith(("__biz=", "mid=", "idx=", "sid=")):
                kept.append(param)
            else:
                dropped.append(param)
        if dropped:
            log.debug("query_params_dropped", count=len(dropped))
        query = "&".join(kept) if kept else ""
    else:
        query = ""

    return urlunparse((scheme, netloc, path, "", query, ""))
