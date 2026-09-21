# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Regression tests for container HIGH findings (OCR report).

Covers: (primary cleanup when fallback.startup fails),
(hybrid_search_engine strategy-None guard),
(init_pipeline uses prompt_loader getter),
(fallback scan_iter duplicate keys).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.cache.fallback import FallbackCachePool


class _FakeClient:
    """Minimal cache client for scan_iter tests."""

    def __init__(self, keys: list[str], fail_after: int | None = None) -> None:
        self._keys = keys
        self._fail_after = fail_after
        self.shutdown_called = False

    async def scan_iter(self, pattern: str, count: int = 100):  # type: ignore[no-untyped-def]
        for i, key in enumerate(self._keys):
            if self._fail_after is not None and i >= self._fail_after:
                raise ConnectionError("redis dropped mid-scan")
            yield key

    async def startup(self) -> None:
        return

    async def shutdown(self) -> None:
        self.shutdown_called = True


class TestFallbackScanIterDedupe:
    """keys yielded before degradation must not re-yield."""

    async def test_no_duplicate_keys_after_mid_scan_failure(self) -> None:
        primary = _FakeClient(["a", "b", "c"], fail_after=2)
        fallback = _FakeClient(["a", "b", "c", "d"])
        pool = FallbackCachePool(primary=primary, fallback=fallback)

        keys = [key async for key in pool.scan_iter("test:*")]

        assert keys == ["a", "b", "c", "d"]
        assert not pool._primary_healthy


class TestContainerPoolsStartupCleanup:
    """fallback startup failure must release the primary client."""

    async def test_primary_shutdown_called_when_fallback_startup_fails(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import core.cache as core_cache
        from container import pools as container_pools

        primary = MagicMock()
        primary.startup = AsyncMock()
        primary.shutdown = AsyncMock()
        fallback = MagicMock()
        fallback.startup = AsyncMock(side_effect=RuntimeError("cashews broken"))
        pool_stub = MagicMock()

        monkeypatch.setattr(core_cache, "RedisClient", lambda url: primary)
        monkeypatch.setattr(core_cache, "CashewsClient", lambda: fallback)
        monkeypatch.setattr(core_cache, "FallbackCachePool", lambda primary, fallback: pool_stub)

        mixin = container_pools.ContainerPoolsMixin.__new__(container_pools.ContainerPoolsMixin)
        mixin._cache_client = None
        mixin._settings = MagicMock(redis=MagicMock(url="redis://localhost:6379/0"))

        with pytest.raises(RuntimeError, match="cashews broken"):
            await mixin.init_cache_client()

        primary.shutdown.assert_awaited_once()
        assert mixin._cache_client is None


class TestHybridSearchEngineStrategyGuard:
    """no RuntimeError when strategy is not initialized."""

    def test_returns_none_when_strategy_missing(self) -> None:
        from container.search import ContainerSearchMixin

        mixin = ContainerSearchMixin.__new__(ContainerSearchMixin)
        mixin._hybrid_engine = None
        mixin._strategy = None
        mixin._settings = MagicMock(search=MagicMock(rerank_enabled=False, mmr_enabled=False))

        assert mixin.hybrid_search_engine() is None


class TestInitPipelinePromptLoader:
    """init_pipeline must use the lazy prompt_loader() getter."""

    def test_prompt_loader_getter_used(self) -> None:
        from pathlib import Path

        source = Path("src/container/services.py").read_text(encoding="utf-8")
        assert "prompt_loader=self.prompt_loader()" in source
        assert "prompt_loader=self._prompt_loader" not in source
