"""Base source parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from modules.source.models import NewsItem, SourceConfig


class BaseSourceParser(ABC):
    """Abstract interface for source parsers (RSS, API, etc.)."""

    @abstractmethod
    async def parse(self, config: SourceConfig) -> list[NewsItem]:
        """Parse a source and return discovered news items.

        Args:
            config: Source configuration.

        Returns:
            List of discovered news items.
        """
        ...
