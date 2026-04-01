# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Base context builder for search operations.

Provides abstract base class and common utilities for building
LLM contexts from knowledge graph data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextSection:
    """A section of search context."""

    name: str
    content: str
    token_count: int = 0
    priority: int = 0
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "content": self.content,
            "token_count": self.token_count,
            "priority": self.priority,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class SearchContext:
    """Complete search context for LLM input.

    Contains multiple sections of context with token budget management.
    """

    query: str
    sections: list[ContextSection] = field(default_factory=list)
    total_tokens: int = 0
    max_tokens: int = 8000
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_section(self, section: ContextSection) -> bool:
        """Add a section if within token budget.

        Returns:
            True if section was added, False if budget exceeded.
        """
        if self.total_tokens + section.token_count > self.max_tokens:
            return False

        self.sections.append(section)
        self.total_tokens += section.token_count
        return True

    def add_content(
        self,
        name: str,
        content: str,
        priority: int = 0,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Add content as a new section.

        Args:
            name: Section name.
            content: Section content.
            priority: Section priority for ordering.
            source: Optional source identifier.
            metadata: Optional metadata dict.

        Returns:
            True if content was added, False if budget exceeded.
        """
        token_count = self._estimate_tokens(content)

        section = ContextSection(
            name=name,
            content=content,
            token_count=token_count,
            priority=priority,
            source=source,
            metadata=metadata or {},
        )

        return self.add_section(section)

    def sort_by_priority(self) -> None:
        """Sort sections by priority (descending)."""
        self.sections.sort(key=lambda s: s.priority, reverse=True)

    def get_available_tokens(self) -> int:
        """Get remaining token budget."""
        return max(0, self.max_tokens - self.total_tokens)

    def to_prompt(self) -> str:
        """Convert to LLM prompt string."""
        lines = [f"Query: {self.query}\n"]

        self.sort_by_priority()

        for section in self.sections:
            lines.append(f"## {section.name}")
            lines.append(section.content)
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "sections": [s.to_dict() for s in self.sections],
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "available_tokens": self.get_available_tokens(),
            "metadata": self.metadata,
        }

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count for text.

        Uses a simple heuristic:
        - Chinese characters: ~1 token each
        - English words: ~0.25 tokens per character
        """
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars

        return chinese_chars + other_chars // 4


class ContextBuilder(ABC):
    """Abstract base class for context builders.

    Context builders construct search contexts from knowledge graph data,
    managing token budgets and content prioritization.
    """

    def __init__(
        self,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
    ) -> None:
        """Initialize context builder.

        Args:
            token_encoder: Optional tokenizer for accurate token counting.
            default_max_tokens: Default maximum tokens for context.
        """
        self._token_encoder = token_encoder
        self._default_max_tokens = default_max_tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Uses tiktoken if available, otherwise estimates.
        """
        if self._token_encoder:
            return len(self._token_encoder.encode(text))

        return SearchContext._estimate_tokens(text)

    def create_context(
        self,
        query: str,
        max_tokens: int | None = None,
    ) -> SearchContext:
        """Create a new search context.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for this context.

        Returns:
            New SearchContext instance.
        """
        return SearchContext(
            query=query,
            max_tokens=max_tokens or self._default_max_tokens,
        )

    @abstractmethod
    async def build(
        self,
        query: str,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> SearchContext:
        """Build search context for a query.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            **kwargs: Additional builder-specific parameters.

        Returns:
            Complete SearchContext ready for LLM input.
        """
        pass

    def format_entity(
        self,
        entity: dict[str, Any],
        include_description: bool = True,
    ) -> str:
        """Format an entity for context inclusion."""
        parts = [f"- {entity.get('canonical_name', 'Unknown')} ({entity.get('type', 'Unknown')})"]

        if include_description and entity.get("description"):
            parts.append(f"  Description: {entity['description']}")

        if entity.get("aliases"):
            aliases = entity["aliases"][:5]
            parts.append(f"  Aliases: {', '.join(aliases)}")

        return "\n".join(parts)

    def format_relationship(
        self,
        relation: dict[str, Any],
    ) -> str:
        """Format a relationship for context inclusion."""
        source = relation.get("source_name", "Unknown")
        target = relation.get("target_name", "Unknown")
        rel_type = relation.get("relation_type", "RELATED_TO")

        return f"- {source} --[{rel_type}]--> {target}"

    def truncate_content(self, content: str, max_tokens: int) -> str:
        """Truncate content to fit within token budget."""
        estimated = self.count_tokens(content)

        if estimated <= max_tokens:
            return content

        target_chars = int(len(content) * max_tokens / estimated)
        truncated = content[:target_chars]

        last_period = truncated.rfind("。")
        last_period_en = truncated.rfind(".")
        last_newline = truncated.rfind("\n")

        cut_point = max(last_period, last_period_en, last_newline)
        if cut_point > target_chars * 0.7:
            truncated = truncated[: cut_point + 1]

        return truncated + "..."
