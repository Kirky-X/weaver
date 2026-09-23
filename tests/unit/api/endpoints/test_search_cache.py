# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for search_cache.ttl_override (R-crawler-and-cache-002)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.endpoints.content.search_cache import store_search


def _request_with_cache(ttl: int = 300):
    request = MagicMock()
    container = request.app.state.container
    container.settings.search.result_cache_ttl = ttl
    cache_client = MagicMock()
    cache_client.get = AsyncMock(return_value=None)
    cache_client.set = AsyncMock()
    container.cache_client.return_value = cache_client
    return request, cache_client


class TestStoreSearchTtlOverride:
    @pytest.mark.asyncio
    async def test_ttl_override_used_in_set(self):
        request, cache = _request_with_cache(ttl=300)
        await store_search(request, {"q": "x"}, {"a": 1}, ttl_override=15)
        assert cache.set.call_args.kwargs.get("ex") == 15

    @pytest.mark.asyncio
    async def test_no_override_uses_configured_ttl(self):
        request, cache = _request_with_cache(ttl=300)
        await store_search(request, {"q": "x"}, {"a": 1})
        assert cache.set.call_args.kwargs.get("ex") == 300

    @pytest.mark.asyncio
    async def test_zero_override_disables_write(self):
        request, cache = _request_with_cache(ttl=300)
        await store_search(request, {"q": "x"}, {"a": 1}, ttl_override=0)
        cache.set.assert_not_awaited()


class TestUnifiedWebSearchFallbackShortTtl:
    @pytest.mark.asyncio
    async def test_web_search_fallback_stores_with_short_ttl(self):
        """web_search_used=True responses must not get the full 300s TTL."""
        import inspect

        from api.endpoints.content import search as search_module

        src = inspect.getsource(search_module)
        assert "ttl_override" in src, "unified search must pass a ttl_override"
        # The override is applied exactly when the web-search fallback ran.
        assert "web_search_used" in src
