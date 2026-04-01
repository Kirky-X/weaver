# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ContextBuilder base class and SearchContext."""

from __future__ import annotations

from modules.knowledge.search.context.builder import (
    ContextBuilder,
    ContextSection,
    SearchContext,
)


class TestContextSection:
    """Tests for ContextSection."""

    def test_to_dict(self) -> None:
        section = ContextSection(name="Test", content="Content", token_count=5, priority=10)
        d = section.to_dict()
        assert d["name"] == "Test"
        assert d["content"] == "Content"
        assert d["token_count"] == 5
        assert d["priority"] == 10

    def test_defaults(self) -> None:
        section = ContextSection(name="A", content="B")
        assert section.token_count == 0
        assert section.priority == 0
        assert section.source is None
        assert section.metadata == {}


class TestSearchContext:
    """Tests for SearchContext."""

    def test_add_section_within_budget(self) -> None:
        ctx = SearchContext(query="test", max_tokens=100)
        section = ContextSection(name="A", content="content", token_count=10)
        assert ctx.add_section(section) is True
        assert ctx.total_tokens == 10

    def test_add_section_exceeds_budget(self) -> None:
        ctx = SearchContext(query="test", max_tokens=5)
        section = ContextSection(name="A", content="content", token_count=100)
        assert ctx.add_section(section) is False
        assert ctx.total_tokens == 0

    def test_add_content(self) -> None:
        ctx = SearchContext(query="test", max_tokens=1000)
        assert ctx.add_content(name="Section", content="Hello world", priority=5) is True
        assert len(ctx.sections) == 1

    def test_add_content_with_metadata(self) -> None:
        ctx = SearchContext(query="test", max_tokens=1000)
        ctx.add_content(name="S", content="c", metadata={"key": "val"})
        assert ctx.sections[0].metadata == {"key": "val"}

    def test_sort_by_priority(self) -> None:
        ctx = SearchContext(query="test", max_tokens=1000)
        ctx.add_content(name="Low", content="l", priority=1)
        ctx.add_content(name="High", content="h", priority=100)
        ctx.sort_by_priority()
        assert ctx.sections[0].name == "High"

    def test_get_available_tokens(self) -> None:
        ctx = SearchContext(query="test", max_tokens=100)
        ctx.add_content(name="S", content="test")
        avail = ctx.get_available_tokens()
        assert avail == 100 - ctx.total_tokens

    def test_to_prompt(self) -> None:
        ctx = SearchContext(query="What is AI?")
        ctx.add_content(name="Context", content="AI is artificial intelligence")
        prompt = ctx.to_prompt()
        assert "What is AI?" in prompt
        assert "Context" in prompt
        assert "AI is artificial intelligence" in prompt

    def test_to_dict(self) -> None:
        ctx = SearchContext(query="test", max_tokens=100)
        d = ctx.to_dict()
        assert d["query"] == "test"
        assert "sections" in d
        assert "total_tokens" in d
        assert "available_tokens" in d

    def test_estimate_tokens_chinese(self) -> None:
        # Each Chinese char ~1 token
        count = SearchContext._estimate_tokens("人工智能")
        assert count == 4

    def test_estimate_tokens_english(self) -> None:
        # English ~0.25 tokens per char
        count = SearchContext._estimate_tokens("hello")
        assert count == 1  # 5 // 4 = 1

    def test_estimate_tokens_mixed(self) -> None:
        count = SearchContext._estimate_tokens("AI人工智能")
        # 4 chinese chars + (6 total - 4 chinese) // 4 = 4 + 0 = 4
        assert count >= 4


class TestContextBuilder:
    """Tests for ContextBuilder base class."""

    def _make_builder(self, **kwargs) -> ContextBuilder:
        """Create a concrete subclass for testing."""

        class ConcreteBuilder(ContextBuilder):
            async def build(self, query, max_tokens=None, **kwargs):
                return self.create_context(query, max_tokens)

        return ConcreteBuilder(**kwargs)

    def test_count_tokens_without_encoder(self) -> None:
        builder = self._make_builder()
        count = builder.count_tokens("hello world")
        assert count > 0

    def test_count_tokens_with_encoder(self) -> None:
        mock_encoder = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        mock_encoder.encode.return_value = [1, 2, 3]
        builder = self._make_builder()
        builder._token_encoder = mock_encoder
        assert builder.count_tokens("test") == 3

    def test_create_context(self) -> None:
        builder = self._make_builder()
        ctx = builder.create_context("query")
        assert ctx.query == "query"
        assert ctx.max_tokens == 8000

    def test_create_context_custom_max_tokens(self) -> None:
        builder = self._make_builder(default_max_tokens=5000)
        ctx = builder.create_context("query", max_tokens=3000)
        assert ctx.max_tokens == 3000

    def test_format_entity(self) -> None:
        builder = self._make_builder()
        entity = {
            "canonical_name": "华为",
            "type": "组织机构",
            "description": "科技公司",
            "aliases": ["Huawei"],
        }
        result = builder.format_entity(entity)
        assert "华为" in result
        assert "组织机构" in result
        assert "科技公司" in result

    def test_format_entity_without_description(self) -> None:
        builder = self._make_builder()
        entity = {"canonical_name": "华为", "type": "组织机构"}
        result = builder.format_entity(entity, include_description=False)
        assert "华为" in result
        assert "Description" not in result

    def test_format_relationship(self) -> None:
        builder = self._make_builder()
        rel = {"source_name": "A", "target_name": "B", "relation_type": "合作"}
        result = builder.format_relationship(rel)
        assert "A" in result
        assert "B" in result
        assert "合作" in result

    def test_truncate_content_short(self) -> None:
        builder = self._make_builder()
        result = builder.truncate_content("short", max_tokens=100)
        assert result == "short"

    def test_truncate_content_long(self) -> None:
        builder = self._make_builder()
        long_text = "人工智能" * 500
        result = builder.truncate_content(long_text, max_tokens=10)
        assert len(result) < len(long_text)
        assert result.endswith("...")
