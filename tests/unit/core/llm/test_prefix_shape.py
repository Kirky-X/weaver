# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for PrefixShape diagnostics module (Task 12)."""

import pytest

from core.llm.prefix_shape import (
    CacheDiagnostics,
    PrefixHashTracker,
    PrefixShape,
    capture_shape,
    compare_shape,
)


class TestPrefixShape:
    """Test PrefixShape dataclass."""

    def test_prefix_shape_construction(self):
        """PrefixShape 构造成功."""
        shape = PrefixShape(
            system_hash="abc12345",
            tools_hash="def67890",
            payload_hash="ghi13579",
            call_point="classifier",
        )
        assert shape.system_hash == "abc12345"
        assert shape.tools_hash == "def67890"
        assert shape.payload_hash == "ghi13579"
        assert shape.call_point == "classifier"

    def test_prefix_hash_property(self):
        """prefix_hash 属性返回 system:tools:payload 拼接的 SHA256 前 16 字符."""
        shape = PrefixShape(
            system_hash="abc12345",
            tools_hash="def67890",
            payload_hash="ghi13579",
            call_point="classifier",
        )
        # prefix_hash should be 16 chars
        assert len(shape.prefix_hash) == 16
        # Should be deterministic
        assert shape.prefix_hash == shape.prefix_hash

    def test_prefix_shape_is_frozen(self):
        """PrefixShape 是 frozen dataclass."""
        shape = PrefixShape(
            system_hash="abc12345",
            tools_hash="def67890",
            payload_hash="ghi13579",
            call_point="classifier",
        )
        with pytest.raises(AttributeError):
            shape.system_hash = "changed"


class TestCaptureShape:
    """Test capture_shape function."""

    def test_capture_shape_returns_8_char_hashes(self):
        """capture_shape 返回 8 字符短哈希."""
        shape = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        assert len(shape.system_hash) == 8
        assert len(shape.payload_hash) == 8
        assert shape.call_point == "classifier"

    def test_capture_shape_tools_schema_none(self):
        """tools_schema=None 时 tools_hash 为固定值."""
        shape = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        # tools_hash should be deterministic for None
        assert len(shape.tools_hash) == 8

    def test_capture_shape_tools_schema_normalized(self):
        """tools_schema 字段顺序不同但内容相同，tools_hash 相同."""
        tools1 = [{"name": "tool1", "type": "function"}, {"name": "tool2", "type": "function"}]
        tools2 = [{"name": "tool2", "type": "function"}, {"name": "tool1", "type": "function"}]

        shape1 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=tools1,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=tools2,
        )
        assert shape1.tools_hash == shape2.tools_hash

    def test_capture_shape_excludes_non_semantic_fields(self):
        """payload 中非语义字段被排除（article_id 不影响 payload_hash）."""
        shape1 = capture_shape(
            "classifier",
            {"content": "test", "article_id": "art-001"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test", "article_id": "art-002"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        assert shape1.payload_hash == shape2.payload_hash


class TestCompareShape:
    """Test compare_shape function."""

    def test_compare_shape_no_history(self):
        """prev=None 时 prefix_changed=False."""
        cur = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        diagnostics = compare_shape(None, cur, server_cache_hit=0, server_cache_miss=100)

        assert diagnostics.prefix_changed is False
        assert diagnostics.change_reasons == []
        assert diagnostics.server_cache_hit == 0
        assert diagnostics.server_cache_miss == 100

    def test_compare_shape_system_changed(self):
        """system prompt 变化检测."""
        shape1 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are an entity extractor",
            tools_schema=None,
        )
        diagnostics = compare_shape(shape1, shape2, server_cache_hit=0, server_cache_miss=100)

        assert diagnostics.prefix_changed is True
        assert "system" in diagnostics.change_reasons

    def test_compare_shape_tools_changed(self):
        """tools schema 变化检测."""
        tools1 = [{"name": "tool1"}]
        tools2 = [{"name": "tool2"}]
        shape1 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=tools1,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=tools2,
        )
        diagnostics = compare_shape(shape1, shape2, server_cache_hit=0, server_cache_miss=100)

        assert diagnostics.prefix_changed is True
        assert "tools" in diagnostics.change_reasons

    def test_compare_shape_payload_changed(self):
        """payload 语义变化检测."""
        shape1 = capture_shape(
            "classifier",
            {"content": "test1"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test2"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        diagnostics = compare_shape(shape1, shape2, server_cache_hit=0, server_cache_miss=100)

        assert diagnostics.prefix_changed is True
        assert "payload" in diagnostics.change_reasons

    def test_compare_shape_no_change(self):
        """无变化时 prefix_changed=False."""
        shape1 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        shape2 = capture_shape(
            "classifier",
            {"content": "test"},
            system_prompt="You are a classifier",
            tools_schema=None,
        )
        diagnostics = compare_shape(shape1, shape2, server_cache_hit=100, server_cache_miss=0)

        assert diagnostics.prefix_changed is False
        assert diagnostics.change_reasons == []


class TestPrefixHashTracker:
    """Test PrefixHashTracker class."""

    def test_first_call_no_history(self):
        """首次调用 changed=False, reasons=[]."""
        tracker = PrefixHashTracker()
        hash_val, changed, reasons = tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        assert len(hash_val) == 16
        assert changed is False
        assert reasons == []

    def test_system_prompt_change_detected(self):
        """system prompt 变化被检测."""
        tracker = PrefixHashTracker()
        tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        hash_val, changed, reasons = tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are an entity extractor",
            payload={"content": "test"},
            tools_schema=None,
        )
        assert changed is True
        assert "system" in reasons

    def test_payload_change_detected(self):
        """payload 语义变化被检测."""
        tracker = PrefixHashTracker()
        tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test1"},
            tools_schema=None,
        )
        hash_val, changed, reasons = tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test2"},
            tools_schema=None,
        )
        assert changed is True
        assert "payload" in reasons

    def test_tools_change_detected(self):
        """tools schema 变化被检测."""
        tracker = PrefixHashTracker()
        tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=[{"name": "tool1"}],
        )
        hash_val, changed, reasons = tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=[{"name": "tool2"}],
        )
        assert changed is True
        assert "tools" in reasons

    def test_multi_call_point_independent(self):
        """多 call_point 独立追踪."""
        tracker = PrefixHashTracker()
        # classifier first call
        tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        # entity_extractor first call (should be independent)
        hash_val, changed, reasons = tracker.compute_prefix_hash(
            "entity_extractor",
            system_prompt="You are an entity extractor",
            payload={"content": "test"},
            tools_schema=None,
        )
        assert changed is False  # First call for entity_extractor
        assert reasons == []

    def test_deterministic_hash(self):
        """相同输入返回相同 hash."""
        tracker1 = PrefixHashTracker()
        tracker2 = PrefixHashTracker()
        hash1, _, _ = tracker1.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        hash2, _, _ = tracker2.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        assert hash1 == hash2

    def test_get_diagnostics(self):
        """get_diagnostics 返回 CacheDiagnostics."""
        tracker = PrefixHashTracker()
        tracker.compute_prefix_hash(
            "classifier",
            system_prompt="You are a classifier",
            payload={"content": "test"},
            tools_schema=None,
        )
        diagnostics = tracker.get_diagnostics("classifier")
        assert isinstance(diagnostics, CacheDiagnostics)
        assert len(diagnostics.prefix_hash) == 16

    def test_get_session_stats(self):
        """get_session_stats 正确聚合多 call_point 统计."""
        tracker = PrefixHashTracker()
        # classifier: 500 hits, 200 misses
        tracker.update_cache_stats("classifier", server_cache_hit=500, server_cache_miss=200)
        # entity_extractor: 300 hits, 100 misses
        tracker.update_cache_stats("entity_extractor", server_cache_hit=300, server_cache_miss=100)

        stats = tracker.get_session_stats()
        assert stats["total_hits"] == 800
        assert stats["total_misses"] == 300
        assert abs(stats["hit_rate"] - 0.7272) < 0.01
