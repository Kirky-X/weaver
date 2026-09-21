# SPDX-License-Identifier: Apache-2.0

# SPDX-FileCopyrightText: © 2026 Kirky.X

"""Tests for stable cache key generator."""

import re


import pytest


from core.llm.client import NON_SEMANTIC_FIELDS, build_stable_cache_key


class TestBuildStableCacheKey:
    """Test build_stable_cache_key function."""

    def test_same_payload_different_article_id_same_key(self):
        """相同 payload（仅 article_id 不同）生成相同 key."""

        payload1 = {"content": "test content", "article_id": "art-001"}

        payload2 = {"content": "test content", "article_id": "art-002"}

        key1 = build_stable_cache_key("classifier", payload1)

        key2 = build_stable_cache_key("classifier", payload2)

        assert key1 == key2

    def test_different_payload_different_key(self):
        """不同 payload 生成不同 key."""

        payload1 = {"content": "content A"}

        payload2 = {"content": "content B"}

        key1 = build_stable_cache_key("classifier", payload1)

        key2 = build_stable_cache_key("classifier", payload2)

        assert key1 != key2

    def test_different_call_point_same_payload_different_key(self):
        """不同 call_point 同 payload 生成不同 key."""

        payload = {"content": "test content"}

        key1 = build_stable_cache_key("classifier", payload)

        key2 = build_stable_cache_key("entity_extractor", payload)

        assert key1 != key2

    def test_key_format_matches_regex(self):
        """缓存键格式: cache:llm:v2:{call_point}:{sha256[:16]}."""

        key = build_stable_cache_key("classifier", {"content": "test"})

        # 格式: cache:llm:v2:classifier:[16 hex chars]

        pattern = r"^cache:llm:v2:classifier:[a-f0-9]{16}$"

        assert re.match(pattern, key), f"Key '{key}' does not match pattern {pattern}"

    def test_non_semantic_fields_excluded(self):
        """非语义字段被排除（timestamp 变化不影响 key）."""

        base_payload = {"content": "test content"}

        payload_with_timestamp = {
            "content": "test content",
            "timestamp": "2026-06-18T10:00:00",
        }

        key1 = build_stable_cache_key("classifier", base_payload)

        key2 = build_stable_cache_key("classifier", payload_with_timestamp)

        assert key1 == key2

    def test_all_non_semantic_fields_excluded(self):
        """所有非语义字段都被排除."""

        non_semantic_values = {
            "article_id": "art-001",
            "task_id": "task-001",
            "timestamp": "2026-06-18T10:00:00",
            "request_id": "req-001",
            "trace_id": "trace-001",
        }

        payload_with_non_semantic = {"content": "test", **non_semantic_values}

        payload_semantic_only = {"content": "test"}

        key1 = build_stable_cache_key("classifier", payload_with_non_semantic)

        key2 = build_stable_cache_key("classifier", payload_semantic_only)

        assert key1 == key2

    def test_field_order_does_not_affect_key(self):
        """字段顺序不影响 key（归一化排序）."""

        payload1 = {"a": 1, "b": 2, "content": "test"}

        payload2 = {"b": 2, "a": 1, "content": "test"}

        key1 = build_stable_cache_key("classifier", payload1)

        key2 = build_stable_cache_key("classifier", payload2)

        assert key1 == key2

    def test_non_semantic_fields_constant(self):
        """NON_SEMANTIC_FIELDS 包含所有 5 个非语义字段."""

        expected_fields = {"article_id", "task_id", "timestamp", "request_id", "trace_id"}

        assert set(NON_SEMANTIC_FIELDS) == expected_fields

    def test_empty_payload(self):
        """空 payload 也能生成有效 key."""

        key = build_stable_cache_key("classifier", {})

        assert key.startswith("cache:llm:v2:classifier:")

    def test_hash_is_16_chars(self):
        """stable_hash 为 16 字符."""

        key = build_stable_cache_key("classifier", {"content": "test"})

        parts = key.split(":")

        # cache:llm:v2:classifier:hash → parts = ["cache", "llm", "v2", "classifier", "hash"]

        stable_hash = parts[-1]

        assert len(stable_hash) == 16


class TestBatchCallCacheKeyConsistency:
    """batch_call 与单次 call() 必须使用同一 _build_cache_key（R-llm-cache-002）."""

    @pytest.mark.asyncio
    async def test_batch_call_uses_build_cache_key(self):
        """batch_call 生成的 Redis key 与 _build_cache_key 输出逐字节一致."""

        import os

        from unittest.mock import AsyncMock, MagicMock, patch

        from core.llm.types import GlobalConfig, Label, LLMType, ProviderConfig, TokenUsage

        def _make_client():

            from core.llm.client import LLMClient

            providers = [
                ProviderConfig(
                    name="openai",
                    type="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    rpm_limit=100,
                    concurrency=5,
                    timeout=30.0,
                    priority=100,
                    weight=100,
                    models={},
                )
            ]

            global_config = GlobalConfig(
                circuit_breaker_threshold=5,
                circuit_breaker_timeout=60.0,
                default_timeout=120.0,
            )

            event_bus = MagicMock()

            event_bus.publish = AsyncMock()

            return LLMClient(
                providers=providers,
                global_config=global_config,
                event_bus=event_bus,
            )

        client = _make_client()

        mock_redis = MagicMock()

        mock_redis.mget = AsyncMock(return_value=[None])

        mock_redis.mset = AsyncMock(return_value=True)

        client._redis = mock_redis

        mock_resp = MagicMock()

        mock_resp.content = "batch result"

        mock_resp.token_usage = TokenUsage(input_tokens=1, output_tokens=1)

        mock_resp.label = Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o")

        mock_resp.latency_ms = 10.0

        mock_resp.model = "gpt-4o"

        mock_resp.cache_usage = None

        payload = {"content": "batch content"}

        # 显式开启 v2：_build_cache_key 产 v2 key，硬编码 v1 的 batch_call 将失配（判别性）

        with patch.dict(os.environ, {"LLM_CACHE_KEY_V2_ENABLED": "true"}):
            with patch.object(
                client._pools["openai"], "execute", new=AsyncMock(return_value=mock_resp)
            ):
                await client.batch_call("chat.openai.gpt-4o", [payload], call_point="classifier")

                mget_keys = mock_redis.mget.call_args[0][0]

                expected_key = client._build_cache_key("classifier", payload)

        assert mget_keys == [expected_key], (
            f"batch_call key {mget_keys[0]!r} != _build_cache_key {expected_key!r}"
        )
