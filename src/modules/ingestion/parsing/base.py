# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base source parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from modules.ingestion.domain.models import NewsItem, SourceConfig


class BaseSourceParser(ABC):
    """Abstract interface for source parsers (RSS, API, etc.)."""

    @abstractmethod
    async def parse(self, config: SourceConfig, force: bool = False) -> list[NewsItem]:
        """Parse a source and return discovered news items.

        Args:
            config: Source configuration.
            force: Force re-fetch even for recently fetched URLs.

        Returns:
            List of discovered news items.
        """
        ...
