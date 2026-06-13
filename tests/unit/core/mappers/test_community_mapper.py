# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for community mappers."""

from __future__ import annotations

import pytest

from core.models.shared import CommunitySearchResultView, CommunityView


class TestCommunityMapper:
    """Tests for CommunityMapper.to_view()."""

    def test_to_view_converts_community_dict(self) -> None:
        """CommunityMapper.to_view() SHALL convert community dict to CommunityView."""
        from core.mappers.community_mapper import CommunityMapper

        data = {
            "id": "comm_001",
            "name": "Test Community",
            "description": "A test community",
            "keywords": ["test", "community"],
            "level": 1,
            "rank": 0.85,
            "entity_count": 10,
            "article_count": 5,
        }
        result = CommunityMapper().to_view(data)
        assert isinstance(result, CommunityView)
        assert result.id == "comm_001"
        assert result.title == "Test Community"
        assert result.summary == "A test community"
        assert result.keywords == ["test", "community"]
        assert result.level == 1
        assert result.rank == 0.85

    def test_to_view_uses_validation_alias(self) -> None:
        """CommunityMapper.to_view() SHALL map 'name' to 'title' via alias."""
        from core.mappers.community_mapper import CommunityMapper

        data = {
            "id": "comm_002",
            "name": "Aliased Title",
            "description": "Aliased summary",
        }
        result = CommunityMapper().to_view(data)
        assert result.title == "Aliased Title"
        assert result.summary == "Aliased summary"

    def test_to_view_defaults(self) -> None:
        """CommunityMapper.to_view() SHALL provide defaults for missing fields."""
        from core.mappers.community_mapper import CommunityMapper

        data = {"id": "comm_003", "name": "Minimal"}
        result = CommunityMapper().to_view(data)
        assert result.keywords == []
        assert result.level == 0
        assert result.rank == 0.0
        assert result.entity_count == 0
        assert result.article_count == 0


class TestCommunitySearchResultMapper:
    """Tests for CommunitySearchResultMapper.to_view()."""

    def test_to_view_converts_search_result_dict(self) -> None:
        """CommunitySearchResultMapper.to_view() SHALL convert to CommunitySearchResultView."""
        from core.mappers.community_search_result_mapper import CommunitySearchResultMapper

        data = {
            "community_id": "comm_001",
            "score": 0.92,
            "title": "Test Community",
            "summary": "A test community summary",
        }
        result = CommunitySearchResultMapper().to_view(data)
        assert isinstance(result, CommunitySearchResultView)
        assert result.community_id == "comm_001"
        assert result.score == 0.92
        assert result.title == "Test Community"
        assert result.summary == "A test community summary"

    def test_to_view_defaults(self) -> None:
        """CommunitySearchResultMapper.to_view() SHALL handle missing optional fields."""
        from core.mappers.community_search_result_mapper import CommunitySearchResultMapper

        data = {
            "community_id": "comm_002",
            "score": 0.75,
        }
        result = CommunitySearchResultMapper().to_view(data)
        assert result.community_id == "comm_002"
        assert result.score == 0.75
        assert result.title is None
        assert result.summary is None

    def test_to_view_converts_score_to_float(self) -> None:
        """CommunitySearchResultMapper.to_view() SHALL convert score to float."""
        from core.mappers.community_search_result_mapper import CommunitySearchResultMapper

        data = {
            "community_id": "comm_003",
            "score": "0.88",
        }
        result = CommunitySearchResultMapper().to_view(data)
        assert result.score == 0.88
        assert isinstance(result.score, float)
