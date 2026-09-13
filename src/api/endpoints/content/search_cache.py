# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Short-TTL response cache for hot search queries (T015).

Caches the ``SearchResponse`` payload of successful unified searches keyed
by the request parameter fingerprint. Disabled entirely when
``search.result_cache_ttl`` is 0 (default 300s); ``no_cache=true`` bypasses
per request. Redis failures degrade to uncached reads.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from fastapi import Request

log = get_logger(__name__)

_CACHE_PREFIX = "search:resp:"


def _cache_config(request: Request) -> tuple[Any | None, int]:
    """Return (cache_client, ttl) for the request; ttl<=0 means disabled."""
    try:
        container = request.app.state.container
        ttl = int(container.settings.search.result_cache_ttl)
        if ttl <= 0:
            return None, 0
        return container.cache_client(), ttl
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        log.debug("search_cache_unavailable", error=str(exc))
        return None, 0


def _fingerprint(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def get_cached_search(request: Request, params: dict[str, Any]) -> dict[str, Any] | None:
    """Return a cached SearchResponse payload dict, or None on miss/bypass."""
    if params.get("no_cache"):
        return None
    cache_client, _ttl = _cache_config(request)
    if cache_client is None:
        return None
    try:
        raw = await cache_client.get(_CACHE_PREFIX + _fingerprint(params))
        if raw:
            log.debug("search_cache_hit", fingerprint=_fingerprint(params))
            return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - degraded cache must not break search
        log.debug("search_cache_read_failed", error=str(exc))
    return None


async def store_search(
    request: Request, params: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Store a SearchResponse payload dict (best-effort)."""
    if params.get("no_cache"):
        return
    cache_client, ttl = _cache_config(request)
    if cache_client is None:
        return
    try:
        await cache_client.set(
            _CACHE_PREFIX + _fingerprint(params),
            json.dumps(payload, ensure_ascii=False, default=str),
            ex=ttl,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("search_cache_write_failed", error=str(exc))
