# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for RuleBasedQualityScorerNode — no LLM dependency."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode
from modules.processing.pipeline.state import PipelineState


def _make_state(
    *,
    has_summary=True,
    has_subjects=True,
    has_key_data=True,
    has_impact=True,
    has_cred_score=True,
    has_source_cred=True,
    has_cross_verification=True,
    has_category=True,
    has_language=True,
    has_region=True,
    is_merged=False,
    body="A " * 200,
    has_event_time=False,
    has_publish_time=False,
) -> PipelineState:
    raw = RawArticle(
        url="https://example.com/test",
        title="Test",
        body="Test body",
        source="test",
        source_host="example.com",
        publish_time=datetime.now(UTC) if has_publish_time else None,
    )
    state = PipelineState(raw=raw)
    si = {}
    if has_summary:
        si["summary"] = "A detailed summary of the article."
    if has_subjects:
        si["subjects"] = ["tech", "AI"]
    if has_key_data:
        si["key_data"] = {"revenue": "1B"}
    if has_impact:
        si["has_data"] = True
    if has_event_time:
        si["event_time"] = datetime.now(UTC).isoformat()
    if si:
        state["summary_info"] = si

    cred = {}
    if has_cred_score:
        cred["score"] = 0.8
    if has_source_cred:
        cred["source_credibility"] = 0.9
    if has_cross_verification:
        cred["cross_verification"] = 0.7
    if cred:
        state["credibility"] = cred

    if has_category:
        state["category"] = "科技"
    if has_language:
        state["language"] = "zh"
    if has_region:
        state["region"] = "CN"

    state["is_merged"] = is_merged
    state["cleaned"] = {"body": body}

    return state


class TestRuleBasedQualityScorerNodeBasic:
    """Basic functionality tests."""

    def test_no_llm_dependency(self):
        """Should not require LLMClient or any LLM dependency."""
        node = RuleBasedQualityScorerNode()
        assert node is not None

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Should score article and update state with quality_score."""
        node = RuleBasedQualityScorerNode()
        state = _make_state()

        result = await node.execute(state)

        assert "quality_score" in result
        assert isinstance(result["quality_score"], float)
        assert 0.0 <= result["quality_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_high_quality_article_scores_high(self):
        """High quality article (all fields complete) should score >= 0.75."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_summary=True,
            has_subjects=True,
            has_key_data=True,
            has_impact=True,
            has_cred_score=True,
            has_source_cred=True,
            has_cross_verification=True,
            has_category=True,
            has_language=True,
            has_region=True,
            is_merged=False,
            body="A " * 200,
            has_event_time=True,
            has_publish_time=True,
        )

        result = await node.execute(state)

        assert result["quality_score"] >= 0.75

    @pytest.mark.asyncio
    async def test_low_quality_article_scores_low(self):
        """Low quality article (no fields) should score <= 0.35."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_summary=False,
            has_subjects=False,
            has_key_data=False,
            has_impact=False,
            has_cred_score=False,
            has_source_cred=False,
            has_cross_verification=False,
            has_category=False,
            has_language=False,
            has_region=False,
            is_merged=False,
            body="",
            has_event_time=False,
            has_publish_time=False,
        )

        result = await node.execute(state)

        assert result["quality_score"] <= 0.35

    @pytest.mark.asyncio
    async def test_merged_article_skips_scoring(self):
        """Merged article should return default score without computing."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(is_merged=True)

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_terminal_state_skips_scoring(self):
        """Terminal article should return default score without computing."""
        node = RuleBasedQualityScorerNode()
        state = _make_state()
        state["terminal"] = True
        state.pop("summary_info", None)

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_preserves_existing_quality_score(self):
        """Should preserve existing quality_score on merged articles."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(is_merged=True)
        state["quality_score"] = 0.9

        result = await node.execute(state)

        assert result["quality_score"] == 0.9


class TestRuleBasedQualityScorerEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_no_summary_info(self):
        """Should handle missing summary_info gracefully."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_summary=False,
            has_subjects=False,
            has_key_data=False,
            has_impact=False,
        )
        state.pop("summary_info", None)

        result = await node.execute(state)

        assert "quality_score" in result
        assert 0.0 <= result["quality_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_no_credibility(self):
        """Should handle missing credibility gracefully."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_cred_score=False,
            has_source_cred=False,
            has_cross_verification=False,
        )
        state.pop("credibility", None)

        result = await node.execute(state)

        assert "quality_score" in result

    @pytest.mark.asyncio
    async def test_preserves_existing_state(self):
        """Should preserve existing state fields."""
        node = RuleBasedQualityScorerNode()
        state = _make_state()
        state["category"] = "tech"
        state["article_id"] = "test-123"

        result = await node.execute(state)

        assert result["category"] == "tech"
        assert result["article_id"] == "test-123"
        assert "quality_score" in result

    @pytest.mark.asyncio
    async def test_short_body_article(self):
        """Short body should still produce a quality score."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(body="Short body")

        result = await node.execute(state)

        assert "quality_score" in result
        assert 0.0 <= result["quality_score"] <= 1.0


class TestRuleBasedQualityScorerCompleteness:
    """Test the completeness dimension specifically."""

    @pytest.mark.asyncio
    async def test_complete_article_max_completeness(self):
        """All completeness fields present should give full completeness score."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_summary=True,
            has_subjects=True,
            has_key_data=True,
            has_impact=True,
            has_cred_score=False,
            has_source_cred=False,
            has_cross_verification=False,
            has_category=False,
            has_language=False,
            has_region=False,
            body="",
            has_event_time=False,
            has_publish_time=False,
        )

        result = await node.execute(state)
        # Only completeness contributes (0.30 * 1.0) + minimal others
        assert result["quality_score"] > 0

    @pytest.mark.asyncio
    async def test_no_completeness_fields(self):
        """No completeness fields should give zero completeness contribution."""
        node = RuleBasedQualityScorerNode()
        state = _make_state(
            has_summary=False,
            has_subjects=False,
            has_key_data=False,
            has_impact=False,
            has_cred_score=False,
            has_source_cred=False,
            has_cross_verification=False,
            has_category=False,
            has_language=False,
            has_region=False,
            body="",
            has_event_time=False,
            has_publish_time=False,
        )

        result = await node.execute(state)

        assert result["quality_score"] <= 0.35
