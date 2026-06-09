# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CategoryDiversity."""

from __future__ import annotations

import pytest

from modules.briefing.diversity import CategoryDiversity


class TestCategoryDiversity:
    """Tests for CategoryDiversity."""

    @pytest.fixture
    def diversity(self):
        """Create a CategoryDiversity instance with max 3 per category."""
        return CategoryDiversity(max_per_category=3)

    def test_empty_articles(self, diversity):
        """Test empty articles returns empty list."""
        result = diversity.apply([])
        assert result == []

    def test_single_article(self, diversity):
        """Test single article is selected."""
        articles = [{"category": "tech", "score": 0.9}]
        result = diversity.apply(articles)
        assert len(result) == 1
        assert result[0] == articles[0]

    def test_max_per_category_enforced(self, diversity):
        """Test max 3 articles per category."""
        articles = [
            {"category": "tech", "id": 1},
            {"category": "tech", "id": 2},
            {"category": "tech", "id": 3},
            {"category": "tech", "id": 4},
            {"category": "tech", "id": 5},
        ]
        result = diversity.apply(articles)
        assert len(result) == 3
        assert [a["id"] for a in result] == [1, 2, 3]

    def test_multiple_categories(self, diversity):
        """Test multiple categories each respect max."""
        articles = [
            {"category": "tech", "id": 1},
            {"category": "tech", "id": 2},
            {"category": "tech", "id": 3},
            {"category": "tech", "id": 4},
            {"category": "sports", "id": 5},
            {"category": "sports", "id": 6},
        ]
        result = diversity.apply(articles)
        assert len(result) == 5
        assert [a["id"] for a in result] == [1, 2, 3, 5, 6]

    def test_unknown_category_default(self, diversity):
        """Test articles without category use 'unknown'."""
        articles = [
            {"id": 1},
            {"id": 2},
            {"category": None, "id": 3},
            {"id": 4},
        ]
        result = diversity.apply(articles)
        assert len(result) == 3

    def test_max_briefing_size(self, diversity):
        """Test max 10 articles total."""
        articles = [{"category": f"cat{i}", "id": i} for i in range(20)]
        result = diversity.apply(articles)
        assert len(result) == 10

    def test_custom_max_per_category(self):
        """Test custom max_per_category."""
        diversity = CategoryDiversity(max_per_category=1)
        articles = [
            {"category": "tech", "id": 1},
            {"category": "tech", "id": 2},
            {"category": "sports", "id": 3},
        ]
        result = diversity.apply(articles)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_preserves_score_order(self, diversity):
        """Test that selected articles maintain their original order."""
        articles = [
            {"category": "tech", "score": 0.9, "id": 1},
            {"category": "sports", "score": 0.8, "id": 2},
            {"category": "tech", "score": 0.7, "id": 3},
            {"category": "tech", "score": 0.6, "id": 4},
            {"category": "tech", "score": 0.5, "id": 5},
        ]
        result = diversity.apply(articles)
        assert [a["id"] for a in result] == [1, 2, 3, 4]
