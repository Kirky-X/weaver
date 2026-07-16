# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for stable cache key generator (Task 10)."""

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
