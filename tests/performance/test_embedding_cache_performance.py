# Copyright (c) 2026 KirkyX. All Rights Reserved
"""性能基准测试：Embedding 缓存批量获取 vs 循环获取"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEmbeddingCachePerformance:
    """Embedding 缓存性能基准测试"""

    @pytest.fixture
    def mock_redis_single_get(self):
        """模拟单次 GET 操作的 Redis 客户端"""
        redis = MagicMock()

        async def mock_get(key):
            # 模拟 1ms 网络延迟
            await asyncio.sleep(0.001)
            return f"cached_{key}"

        redis.get = AsyncMock(side_effect=mock_get)
        return redis

    @pytest.fixture
    def mock_redis_batch_get(self):
        """模拟批量 MGET 操作的 Redis 客户端"""
        redis = MagicMock()

        async def mock_mget(keys):
            # 模拟 1ms 网络延迟（批量操作只需一次网络往返）
            await asyncio.sleep(0.001)
            return [f"cached_{key}" for key in keys]

        redis.mget = AsyncMock(side_effect=mock_mget)
        return redis

    @pytest.mark.asyncio
    @pytest.mark.parametrize("count", [10, 50, 100, 500])
    async def test_single_get_performance(self, mock_redis_single_get, count):
        """测试循环 GET 性能"""
        keys = [f"cache:key:{i}" for i in range(count)]

        start = time.perf_counter()
        results = []
        for key in keys:
            result = await mock_redis_single_get.get(key)
            results.append(result)
        elapsed = time.perf_counter() - start

        print(f"\n循环 GET ({count} 条): {elapsed * 1000:.2f}ms")
        assert len(results) == count

    @pytest.mark.asyncio
    @pytest.mark.parametrize("count", [10, 50, 100, 500])
    async def test_batch_get_performance(self, mock_redis_batch_get, count):
        """测试批量 MGET 性能"""
        keys = [f"cache:key:{i}" for i in range(count)]

        start = time.perf_counter()
        results = await mock_redis_batch_get.mget(keys)
        elapsed = time.perf_counter() - start

        print(f"\n批量 MGET ({count} 条): {elapsed * 1000:.2f}ms")
        assert len(results) == count

    @pytest.mark.asyncio
    async def test_performance_comparison(self, mock_redis_single_get, mock_redis_batch_get):
        """性能对比测试"""
        results = []

        for count in [10, 50, 100, 500]:
            keys = [f"cache:key:{i}" for i in range(count)]

            # 循环 GET
            start = time.perf_counter()
            for key in keys:
                await mock_redis_single_get.get(key)
            single_time = time.perf_counter() - start

            # 批量 MGET
            start = time.perf_counter()
            await mock_redis_batch_get.mget(keys)
            batch_time = time.perf_counter() - start

            speedup = single_time / batch_time if batch_time > 0 else 0
            results.append(
                {
                    "count": count,
                    "single_ms": single_time * 1000,
                    "batch_ms": batch_time * 1000,
                    "speedup": speedup,
                }
            )

        print("\n" + "=" * 60)
        print("Embedding 缓存性能对比 (模拟 1ms 网络延迟)")
        print("=" * 60)
        print(f"{'数量':>6} | {'循环 GET':>12} | {'批量 MGET':>12} | {'提升':>8}")
        print("-" * 60)
        for r in results:
            print(
                f"{r['count']:>6} | {r['single_ms']:>10.2f}ms | {r['batch_ms']:>10.2f}ms | {r['speedup']:>7.1f}x"
            )
        print("=" * 60)

        # 验证批量获取确实更快
        for r in results:
            assert r["batch_ms"] < r["single_ms"], f"批量获取应比循环获取更快: {r}"
