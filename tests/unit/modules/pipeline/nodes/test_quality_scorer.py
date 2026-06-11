# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RuleBasedQualityScorerNode."""

from __future__ import annotations

import pytest

from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode
from modules.processing.pipeline.state import PipelineState


class TestRuleBasedQualityScorerNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, sample_raw):
        """Should score article and update state.

        State setup for score 0.85:
        - completeness: 3/4 = 0.75 → 0.75 * 0.30 = 0.225
        - credibility: 3/3 = 1.0  → 1.0  * 0.25 = 0.25
        - normativity: 3/3 = 1.0  → 1.0  * 0.20 = 0.20
        - originality: body ≤ 100 → 0.5  → 0.5  * 0.15 = 0.075
        - timeliness: has publish_time → 1.0 → 1.0 * 0.10 = 0.10
        Total: 0.225 + 0.25 + 0.20 + 0.075 + 0.10 = 0.85
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["summary_info"] = {
            "summary": "A summary",
            "subjects": ["tech"],
            "key_data": {"key": "value"},
        }
        state["credibility"] = {
            "score": 0.9,
            "source_credibility": 0.8,
            "cross_verification": 0.7,
        }
        state["category"] = "tech"
        state["language"] = "en"
        state["region"] = "US"
        state["cleaned"] = {"title": "Title", "body": "Short body", "publish_time": "2024-01-01"}

        result = await node.execute(state)

        assert "quality_score" in result
        assert result["quality_score"] == 0.85

    @pytest.mark.asyncio
    async def test_default_score_on_terminal(self, sample_raw):
        """Should use default score 0.5 on terminal state."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_default_score_on_merged(self, sample_raw):
        """Should use default score 0.5 on merged state."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5


class TestRuleBasedQualityScorerNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, sample_raw):
        """Should skip processing if terminal flag is set."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_skips_merged_articles(self, sample_raw):
        """Should skip processing for merged articles."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_minimal_state_score(self, sample_raw):
        """Should compute low score with minimal state.

        - completeness: 0/4 = 0.0 → 0.0 * 0.30 = 0
        - credibility: 0/3 = 0.0 → 0.0 * 0.25 = 0
        - normativity: 0/3 = 0.0 → 0.0 * 0.20 = 0
        - originality: body ≤ 100 → 0.5 → 0.5 * 0.15 = 0.075
        - timeliness: no time → 0.5 → 0.5 * 0.10 = 0.05
        Total: 0.075 + 0.05 = 0.125 → round = 0.12
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.12

    @pytest.mark.asyncio
    async def test_full_state_max_score(self, sample_raw):
        """Should score 1.0 with all fields present.

        - completeness: 4/4 = 1.0 → 1.0 * 0.30 = 0.30
        - credibility: 3/3 = 1.0 → 1.0 * 0.25 = 0.25
        - normativity: 3/3 = 1.0 → 1.0 * 0.20 = 0.20
        - originality: body > 100 → 1.0 → 1.0 * 0.15 = 0.15
        - timeliness: has publish_time → 1.0 → 1.0 * 0.10 = 0.10
        Total: 1.0
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["summary_info"] = {
            "summary": "A summary",
            "subjects": ["tech"],
            "key_data": {"key": "value"},
            "has_data": True,
        }
        state["credibility"] = {
            "score": 0.9,
            "source_credibility": 0.8,
            "cross_verification": 0.7,
        }
        state["category"] = "tech"
        state["language"] = "en"
        state["region"] = "US"
        state["cleaned"] = {
            "title": "Title",
            "body": "A" * 200,
            "publish_time": "2024-01-01",
        }

        result = await node.execute(state)

        assert result["quality_score"] == 1.0

    @pytest.mark.asyncio
    async def test_long_body_high_originality(self, sample_raw):
        """Should give high originality for long body text.

        - completeness: 0, credibility: 0, normativity: 0
        - originality: body > 100 → 1.0 → 1.0 * 0.15 = 0.15
        - timeliness: no time → 0.5 → 0.5 * 0.10 = 0.05
        Total: 0.15 + 0.05 = 0.20
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "A" * 200}

        result = await node.execute(state)

        assert result["quality_score"] == 0.20


class TestRuleBasedQualityScorerNodeErrorHandling:
    """Tests for missing data scenarios."""

    @pytest.mark.asyncio
    async def test_no_cleaned_data(self, sample_raw):
        """Should handle missing cleaned data gracefully.

        - completeness: 0, credibility: 0, normativity: 0
        - originality: no body → 0.3 → 0.3 * 0.15 = 0.045
        - timeliness: no time → 0.5 → 0.5 * 0.10 = 0.05
        Total: 0.045 + 0.05 = 0.095 → round = 0.1
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["quality_score"] == 0.1

    @pytest.mark.asyncio
    async def test_missing_summary_info(self, sample_raw):
        """Should handle missing summary_info.

        - completeness: 0/4 = 0 → 0
        - credibility: 3/3 = 1.0 → 0.25
        - normativity: 3/3 = 1.0 → 0.20
        - originality: body > 100 → 1.0 → 0.15
        - timeliness: has publish_time → 1.0 → 0.10
        Total: 0.70
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["credibility"] = {
            "score": 0.9,
            "source_credibility": 0.8,
            "cross_verification": 0.7,
        }
        state["category"] = "tech"
        state["language"] = "en"
        state["region"] = "US"
        state["cleaned"] = {
            "title": "Title",
            "body": "A" * 200,
            "publish_time": "2024-01-01",
        }

        result = await node.execute(state)

        assert result["quality_score"] == 0.70

    @pytest.mark.asyncio
    async def test_missing_credibility(self, sample_raw):
        """Should handle missing credibility data.

        - completeness: 4/4 = 1.0 → 0.30
        - credibility: 0/3 = 0 → 0
        - normativity: 3/3 = 1.0 → 0.20
        - originality: body > 100 → 1.0 → 0.15
        - timeliness: has publish_time → 1.0 → 0.10
        Total: 0.75
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["summary_info"] = {
            "summary": "A summary",
            "subjects": ["tech"],
            "key_data": {"key": "value"},
            "has_data": True,
        }
        state["category"] = "tech"
        state["language"] = "en"
        state["region"] = "US"
        state["cleaned"] = {
            "title": "Title",
            "body": "A" * 200,
            "publish_time": "2024-01-01",
        }

        result = await node.execute(state)

        assert result["quality_score"] == 0.75


class TestRuleBasedQualityScorerNodeIntegration:
    """Integration-like tests."""

    @pytest.mark.asyncio
    async def test_preserves_existing_state(self, sample_raw):
        """Should preserve existing state fields."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["summary_info"] = {
            "summary": "A summary",
            "subjects": ["tech"],
            "key_data": {"key": "value"},
            "has_data": True,
        }
        state["category"] = "tech"
        state["language"] = "en"
        state["region"] = "US"
        state["cleaned"] = {
            "title": "Title",
            "body": "A" * 200,
            "publish_time": "2024-01-01",
        }
        state["article_id"] = "test-123"

        result = await node.execute(state)

        assert result["article_id"] == "test-123"
        assert result["quality_score"] == 0.75

    @pytest.mark.asyncio
    async def test_existing_quality_score_preserved_on_terminal(self, sample_raw):
        """Should not overwrite existing quality_score on terminal state."""
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["quality_score"] = 0.9

        result = await node.execute(state)

        assert result["quality_score"] == 0.9

    @pytest.mark.asyncio
    async def test_completeness_dimension(self, sample_raw):
        """Should weight completeness at 30%.

        - completeness: 4/4 = 1.0 → 0.30
        - credibility: 0, normativity: 0
        - originality: body ≤ 100 → 0.5 → 0.075
        - timeliness: no time → 0.5 → 0.05
        Total: 0.30 + 0.075 + 0.05 = 0.425 → round = 0.42
        """
        node = RuleBasedQualityScorerNode()
        state = PipelineState(raw=sample_raw)
        state["summary_info"] = {
            "summary": "A summary",
            "subjects": ["tech"],
            "key_data": {"key": "value"},
            "has_data": True,
        }
        state["cleaned"] = {"title": "Title", "body": "Short"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.42
