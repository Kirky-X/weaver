# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ConflictDetectorNode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.processing.nodes.quality.conflict_detector import ConflictDetectorNode
from modules.processing.pipeline.state import PipelineState


class TestConflictDetectorNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_detects_numerical_conflict(self, sample_raw):
        """Should detect numerical conflicts between articles."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"body": "数据显示增长30%"}
        state["category"] = "economy"

        node._find_similar = AsyncMock(
            return_value=[{"title": "Other Report", "body": "数据显示增长20%"}]
        )

        result = await node.execute(state)

        assert "data_conflicts" in result
        assert len(result["data_conflicts"]) >= 1
        growth_conflicts = [c for c in result["data_conflicts"] if c["attribute"] == "growth"]
        assert len(growth_conflicts) >= 1
        conflict = growth_conflicts[0]
        assert conflict["value_a"] == 30.0
        assert conflict["value_b"] == 20.0
        assert conflict["delta_pct"] == pytest.approx(33.3, rel=0.1)

    @pytest.mark.asyncio
    async def test_same_attribute_matches_same_type(self):
        """_same_attribute should match claims of the same type."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"type": "percent", "value": 30.0, "text": "30%"}
        c2 = {"type": "percent", "value": 20.0, "text": "20%"}
        assert node._same_attribute(c1, c2) is True

    @pytest.mark.asyncio
    async def test_same_attribute_rejects_different_type(self):
        """_same_attribute should reject claims of different types."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"type": "percent", "value": 30.0, "text": "30%"}
        c2 = {"type": "growth", "value": 30.0, "text": "增长30%"}
        assert node._same_attribute(c1, c2) is False

    @pytest.mark.asyncio
    async def test_no_numerical_claims_returns_unchanged_state(self, sample_raw):
        """Should return state unchanged when no numerical claims found."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"body": "纯文本内容，没有数字声明"}

        result = await node.execute(state)

        assert "data_conflicts" not in result

    @pytest.mark.asyncio
    async def test_extracts_percent_claims(self):
        """Should extract percentage claims from text."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        claims = node._extract_claims("增长30% 下降10%")
        percents = [c for c in claims if c["type"] == "percent"]
        assert len(percents) == 2
        assert any(c["value"] == 30.0 for c in percents)
        assert any(c["value"] == 10.0 for c in percents)

    @pytest.mark.asyncio
    async def test_delta_below_threshold_ignored(self, sample_raw):
        """Should ignore conflicts below 20% delta threshold."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"body": "经济增长30%"}
        state["category"] = "economy"

        node._find_similar = AsyncMock(
            return_value=[{"title": "Other Report", "body": "经济增长28%"}]
        )

        result = await node.execute(state)

        assert "data_conflicts" not in result


class TestConflictDetectorNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, sample_raw):
        """Should skip processing if terminal flag is set."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"body": "经济增长30%"}
        state["category"] = "economy"

        result = await node.execute(state)

        assert "data_conflicts" not in result

    @pytest.mark.asyncio
    async def test_skips_merged_articles(self, sample_raw):
        """Should skip processing for merged articles."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"body": "经济增长30%"}
        state["category"] = "economy"

        result = await node.execute(state)

        assert "data_conflicts" not in result

    @pytest.mark.asyncio
    async def test_handles_empty_body(self, sample_raw):
        """Should handle empty body without error."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"body": ""}

        result = await node.execute(state)

        assert "data_conflicts" not in result

    @pytest.mark.asyncio
    async def test_handles_missing_cleaned(self, sample_raw):
        """Should handle missing cleaned key without error."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "data_conflicts" not in result

    @pytest.mark.asyncio
    async def test_extracts_growth_claims(self):
        """Should extract growth pattern claims."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        claims = node._extract_claims("GDP增长了15%")
        growth = [c for c in claims if c["type"] == "growth"]
        assert len(growth) == 1
        assert growth[0]["value"] == 15.0

    @pytest.mark.asyncio
    async def test_extracts_decline_claims(self):
        """Should extract decline pattern claims."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        claims = node._extract_claims("失业率下降了2.5%")
        decline = [c for c in claims if c["type"] == "decline"]
        assert len(decline) >= 1
        assert decline[0]["value"] == 2.5

    @pytest.mark.asyncio
    async def test_no_category_skips_similar_search(self, sample_raw):
        """Should skip similar article search when no category."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"body": "经济增长30%"}

        result = await node.execute(state)

        assert "data_conflicts" not in result
