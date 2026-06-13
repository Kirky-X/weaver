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
        """Estimate token count for text using tiktoken.

        Falls back to simple heuristic if tiktoken is unavailable:
        - Chinese characters: ~1 token each
        - English words: ~0.25 tokens per character
        """
        # Use cached encoding if available
        if not hasattr(SearchContext, "_tiktoken_encoding"):
            try:
                import tiktoken

                from core.constants import TiktokenEncoding

                SearchContext._tiktoken_encoding = tiktoken.get_encoding(
                    TiktokenEncoding.CL100K_BASE
                )
            except Exception:
                log.warning("tiktoken_encoding_init_failed", exc_info=True)
                SearchContext._tiktoken_encoding = None

        if SearchContext._tiktoken_encoding:
            return len(SearchContext._tiktoken_encoding.encode(text))

        # Fallback to heuristic
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

    async def fetch_article_bodies(
        self,
        pg_ids: list[str],
        article_repo: Any = None,
    ) -> dict[str, str]:
        """Fetch article body content from PostgreSQL by pg_ids.

        Args:
            pg_ids: List of PostgreSQL article IDs.
            article_repo: Optional ArticleRepo override. Falls back to self._article_repo.

        Returns:
            Dict mapping pg_id to body content.
        """
        repo = article_repo or getattr(self, "_article_repo", None)
        if not repo or not pg_ids:
            return {}

        bodies: dict[str, str] = {}
        for pg_id in pg_ids[:5]:
            try:
                article = await repo.get(pg_id)
                if article and article.body:
                    bodies[str(pg_id)] = article.body
            except Exception as exc:
                from core.observability import get_logger

                get_logger(__name__).warning("fetch_body_failed", pg_id=pg_id, error=str(exc))
        return bodies

    def extract_key_excerpt(
        self,
        body: str,
        entity_names: list[str],
        max_tokens: int = 300,
    ) -> str:
        """Extract key excerpt from article body.

        Extracts sentences containing entity mentions, falling back to
        head/tail truncation when no matches found.

        Args:
            body: Full article body text.
            entity_names: Entity names to match in sentences.
            max_tokens: Maximum tokens for excerpt.

        Returns:
            Truncated excerpt with entity-relevant content prioritized.
        """
        import re

        sentences = re.split(r"(?<=[。！？.!?\n])", body)
        matched: list[str] = []
        others: list[str] = []

        for s in sentences:
            s = s.strip()
            if not s:
                continue
            lower_s = s.lower()
            if any(n.lower() in lower_s for n in entity_names):
                matched.append(s)
            else:
                others.append(s)

        selected = matched[:8]
        if len(selected) < 4:
            selected.extend(others[: 4 - len(selected)])

        excerpt = "".join(selected)
        return self.truncate_content(excerpt, max_tokens)

    def format_entities_section(
        self,
        entities: list[dict[str, Any]],
        include_description: bool = True,
    ) -> str:
        """Format entities section for context."""
        lines = []
        for entity in entities:
            lines.append(self.format_entity(entity, include_description))
        return "\n".join(lines)

    def format_relationships_section(
        self,
        relationships: list[dict[str, Any]],
        include_direction: bool = False,
    ) -> str:
        """Format relationships section for context.

        Args:
            relationships: List of relationship dicts.
            include_direction: If True, show direction indicator (双向/单向).

        Returns:
            Formatted relationships string.
        """
        lines = []
        for rel in relationships:
            if include_direction:
                lines.append(self.format_relation_with_direction(rel))
            else:
                source = rel.get("source_name", "Unknown")
                target = rel.get("target_name", "Unknown")
                rel_type = rel.get("relation_type", "RELATED_TO")
                lines.append(f"- {source} --[{rel_type}]--> {target}")
        return "\n".join(lines)

    def format_articles_section(
        self,
        articles: list[dict[str, Any]],
    ) -> str:
        """Format articles section with body excerpt."""
        lines = []
        for article in articles:
            title = article.get("title", "Unknown")
            summary = article.get("summary", "")
            body_excerpt = article.get("body_excerpt", "")

            lines.append(f"- {title}")
            if summary:
                truncated = self.truncate_content(summary, 200)
                lines.append(f"  概要: {truncated}")
            if body_excerpt:
                lines.append(f"  原文片段: {body_excerpt}")
        return "\n".join(lines)

    @staticmethod
    def is_known_symmetric(name_en: str) -> bool:
        """Check if a relation type is known to be symmetric."""
        symmetric_types = {
            "PARTNERS_WITH",
            "COLLABORATES_WITH",
            "RELATED_TO",
            "COOPERATES_WITH",
            "ALLIED_WITH",
            "ASSOCIATED_WITH",
        }
        return name_en in symmetric_types

    @staticmethod
    def format_relation_with_direction(rel: dict[str, Any]) -> str:
        """Format a relationship with direction indicator.

        Returns:
            Formatted string like:
                - 华为 --[合作(双向)]--> 比亚迪
        """
        source = rel.get("source_name", "Unknown")
        target = rel.get("target_name", "Unknown")
        rel_type = rel.get("relation_type", "RELATED_TO")
        is_symmetric = rel.get("is_symmetric", False)

        direction = "双向" if is_symmetric else "单向"
        return f"- {source} --[{rel_type}({direction})]--> {target}"

    def format_communities_section(
        self,
        communities: list[dict[str, Any]],
    ) -> str:
        """Format communities section for context."""
        lines = []
        for i, comm in enumerate(communities, 1):
            title = comm.get("title", f"Community {i}")
            summary = comm.get("summary", "")
            entity_count = comm.get("entity_count", 0)

            lines.append(f"### {title}")
            lines.append(f"Entities: {entity_count}")
            if summary:
                truncated = self.truncate_content(summary, 200)
                lines.append(f"Summary: {truncated}")
            lines.append("")

        return "\n".join(lines)

    def format_cross_community_section(
        self,
        connections: list[dict[str, Any]],
        include_direction: bool = False,
    ) -> str:
        """Format cross-community connections section.

        Args:
            connections: List of connection dicts.
            include_direction: If True, show direction indicator.

        Returns:
            Formatted connections string.
        """
        lines = []
        for conn in connections:
            source_comm = conn.get("source_community", "Unknown")
            target_comm = conn.get("target_community", "Unknown")
            source_entity = conn.get("source_entity", "Unknown")
            target_entity = conn.get("target_entity", "Unknown")
            rel_type = conn.get("relation_type", "RELATED_TO")

            if include_direction:
                is_symmetric = self.is_known_symmetric(rel_type)
                direction = "双向" if is_symmetric else "单向"
                lines.append(
                    f"- [{source_comm}] {source_entity} --[{rel_type}({direction})]--> {target_entity} [{target_comm}]"
                )
            else:
                lines.append(
                    f"- [{source_comm}] {source_entity} --[{rel_type}]--> {target_entity} [{target_comm}]"
                )

        return "\n".join(lines)
