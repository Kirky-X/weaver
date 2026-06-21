# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Protocol return type declarations.

Verifies that Protocol interfaces declare the correct View return types
instead of raw dict[str, Any] or list[Any].
"""

from __future__ import annotations

import inspect
from typing import Any, get_type_hints

import pytest

from core.models.shared import (
    ArticleSearchResultView,
    CommunitySearchResultView,
    EntitySearchResultView,
    EntityView,
)
from core.protocols.repositories import (
    EntityRepository,
    VectorRepository,
)

# Build a namespace with all View types for resolving forward references
_TYPE_NS = {
    "EntityView": EntityView,
    "ArticleSearchResultView": ArticleSearchResultView,
    "EntitySearchResultView": EntitySearchResultView,
    "CommunitySearchResultView": CommunitySearchResultView,
}


def _get_return_type_str(method: Any) -> str:
    """Get the string representation of a method's return type hint."""
    try:
        hints = get_type_hints(method, localns=_TYPE_NS)
    except NameError:
        # Fallback: inspect the source code for the return annotation
        source = inspect.getsource(method)
        for line in source.split("\n"):
            if "->" in line:
                _, after = line.split("->", 1)
                return after.split(":")[0].strip()
        return ""
    return_type = hints.get("return")
    return str(return_type) if return_type is not None else ""


class TestEntityRepositoryReturnTypes:
    """Verify EntityRepository Protocol declares View return types."""

    def test_find_entity_returns_entity_view_or_none(self) -> None:
        """find_entity() SHALL return EntityView | None."""
        return_str = _get_return_type_str(EntityRepository.find_entity)
        assert (
            "EntityView" in return_str
        ), f"find_entity() should return EntityView | None, got {return_str}"

    def test_find_entity_by_id_returns_entity_view_or_none(self) -> None:
        """find_entity_by_id() SHALL return EntityView | None."""
        return_str = _get_return_type_str(EntityRepository.find_entity_by_id)
        assert (
            "EntityView" in return_str
        ), f"find_entity_by_id() should return EntityView | None, got {return_str}"

    def test_find_entities_batch_returns_list_entity_view(self) -> None:
        """find_entities_batch() SHALL return list[EntityView]."""
        return_str = _get_return_type_str(EntityRepository.find_entities_batch)
        assert (
            "EntityView" in return_str
        ), f"find_entities_batch() should return list[EntityView], got {return_str}"
        assert (
            "dict" not in return_str
        ), f"find_entities_batch() should not return dict type, got {return_str}"


class TestVectorRepositoryReturnTypes:
    """Verify VectorRepository Protocol declares View return types."""

    def test_find_similar_returns_list_article_search_result_view(self) -> None:
        """find_similar() SHALL return list[ArticleSearchResultView]."""
        return_str = _get_return_type_str(VectorRepository.find_similar)
        assert (
            "ArticleSearchResultView" in return_str
        ), f"find_similar() should return list[ArticleSearchResultView], got {return_str}"
        assert (
            "Any" not in return_str
        ), f"find_similar() should not return list[Any], got {return_str}"

    def test_find_similar_entities_returns_list_entity_search_result_view(self) -> None:
        """find_similar_entities() SHALL return list[EntitySearchResultView]."""
        return_str = _get_return_type_str(VectorRepository.find_similar_entities)
        assert (
            "EntitySearchResultView" in return_str
        ), f"find_similar_entities() should return list[EntitySearchResultView], got {return_str}"
        assert (
            "Any" not in return_str
        ), f"find_similar_entities() should not return list[Any], got {return_str}"
