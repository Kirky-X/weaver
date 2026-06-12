# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for ArticleView type correctness.

Covers:
- verified_by_sources should be int, not bool
"""

from __future__ import annotations

import inspect

from core.models.shared import ArticleView


class TestArticleViewType:
    """Test ArticleView field types."""

    def test_verified_by_sources_is_int(self):
        """verified_by_sources should be int type."""
        # Get the field info from the model
        field_info = ArticleView.model_fields.get("verified_by_sources")
        assert field_info is not None, "verified_by_sources field not found"

        # Check the annotation
        hints = get_type_hints(ArticleView)
        annotation = hints.get("verified_by_sources")
        assert annotation is int, f"Expected int, got {annotation}"

    def test_verified_by_sources_default_value(self):
        """verified_by_sources default should be 0."""
        # Create an instance without specifying verified_by_sources
        article = ArticleView(
            id="00000000-0000-0000-0000-000000000001",
            source_url="https://example.com/article1",
            title="Test Article",
        )
        assert article.verified_by_sources == 0
        assert isinstance(article.verified_by_sources, int)

    def test_verified_by_sources_accepts_int(self):
        """verified_by_sources should accept integer values."""
        article = ArticleView(
            id="00000000-0000-0000-0000-000000000001",
            source_url="https://example.com/article1",
            title="Test Article",
            verified_by_sources=3,
        )
        assert article.verified_by_sources == 3
        assert isinstance(article.verified_by_sources, int)


def get_type_hints(model):
    """Get type hints for a Pydantic model."""
    hints = {}
    for name, field in model.model_fields.items():
        hints[name] = field.annotation
    return hints
