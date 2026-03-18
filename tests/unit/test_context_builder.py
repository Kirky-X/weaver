# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for context builder module."""

from modules.search.context.builder import (
    ContextSection,
    SearchContext,
)


class TestContextSection:
    """Test ContextSection dataclass."""

    def test_initialization(self):
        """Test ContextSection initialization."""
        section = ContextSection(
            name="Test Section",
            content="Test content",
            token_count=10,
            priority=5,
        )

        assert section.name == "Test Section"
        assert section.content == "Test content"
        assert section.token_count == 10
        assert section.priority == 5

    def test_to_dict(self):
        """Test ContextSection to_dict."""
        section = ContextSection(name="Test", content="Content", priority=1)
        d = section.to_dict()

        assert d["name"] == "Test"
        assert d["content"] == "Content"
        assert d["priority"] == 1


class TestSearchContext:
    """Test SearchContext class."""

    def test_initialization(self):
        """Test SearchContext initialization."""
        context = SearchContext(query="test query", max_tokens=5000)

        assert context.query == "test query"
        assert context.max_tokens == 5000
        assert context.total_tokens == 0

    def test_add_section(self):
        """Test adding section within budget."""
        context = SearchContext(query="test", max_tokens=1000)

        section = ContextSection(name="Test", content="Content", token_count=50)
        added = context.add_section(section)

        assert added is True
        assert context.total_tokens == 50

    def test_add_section_exceeds_budget(self):
        """Test adding section exceeds budget."""
        context = SearchContext(query="test", max_tokens=100)

        section = ContextSection(name="Test", content="Content", token_count=150)
        added = context.add_section(section)

        assert added is False
        assert context.total_tokens == 0

    def test_add_content(self):
        """Test adding content directly."""
        context = SearchContext(query="test", max_tokens=1000)

        added = context.add_content(name="Entities", content="Entity1, Entity2", priority=10)

        assert added is True
        assert len(context.sections) == 1

    def test_sort_by_priority(self):
        """Test sorting by priority."""
        context = SearchContext(query="test", max_tokens=1000)

        context.add_content(name="Low", content="Low content", priority=1)
        context.add_content(name="High", content="High content", priority=10)
        context.add_content(name="Medium", content="Medium content", priority=5)

        context.sort_by_priority()

        assert context.sections[0].name == "High"
        assert context.sections[1].name == "Medium"
        assert context.sections[2].name == "Low"

    def test_get_available_tokens(self):
        """Test available tokens calculation."""
        context = SearchContext(query="test", max_tokens=1000)
        context.add_content(name="Test", content="x" * 100, priority=1)

        available = context.get_available_tokens()

        assert available < 1000

    def test_to_prompt(self):
        """Test prompt generation."""
        context = SearchContext(query="test query", max_tokens=1000)
        context.add_content(name="Section1", content="Content1", priority=10)
        context.add_content(name="Section2", content="Content2", priority=5)

        prompt = context.to_prompt()

        assert "test query" in prompt
        assert "Section1" in prompt
        assert "Section2" in prompt

    def test_to_dict(self):
        """Test context serialization."""
        context = SearchContext(query="test", max_tokens=1000)
        context.add_content(name="Test", content="Content", priority=1)

        d = context.to_dict()

        assert d["query"] == "test"
        assert len(d["sections"]) == 1


class TestContextBuilderBase:
    """Test ContextBuilder base class utilities."""

    def test_estimate_tokens(self):
        """Test token estimation."""
        tokens = SearchContext._estimate_tokens("你好世界")

        assert tokens > 0

    def test_estimate_tokens_mixed(self):
        """Test token estimation with mixed content."""
        tokens = SearchContext._estimate_tokens("Hello 你好")

        assert tokens > 0
