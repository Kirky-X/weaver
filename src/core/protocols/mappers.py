# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Mapper protocol definitions for unified data mapping.

This module defines the MapperProtocol that all Mapper classes must implement.
Mapper classes convert raw data (ORM rows, dicts) into typed View models,
providing a consistent interface for data transformation across the system.

All implementations MUST explicitly declare their protocol implementation
in their docstring using the "Implements:" section.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

ViewT = TypeVar("ViewT")


@runtime_checkable
class MapperProtocol(Protocol):
    """Protocol for data mapping from raw sources to View models.

    Mapper classes convert raw data (ORM rows, dicts from Neo4j/graph DBs)
    into typed Pydantic View models with field-level type conversion.

    Implementations:
        - PostgresArticleMapper: Maps PostgreSQL ORM rows/dicts to ArticleView
        - Neo4jEntityMapper: Maps Neo4j records to EntityView
        - CommunityMapper: Maps community data to CommunityView
        - CommunitySearchResultMapper: Maps search results to CommunitySearchResultView
    """

    def to_view(self, data: Any) -> Any:
        """Convert raw data to a typed View model.

        Args:
            data: Raw data source (ORM row, dict, or other structure).

        Returns:
            A typed View model instance (ArticleView, EntityView, etc.).
        """
        ...
