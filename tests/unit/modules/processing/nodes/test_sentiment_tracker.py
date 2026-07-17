# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SentimentTrackerNode (T003).

Verifies:
- Article-level sentiment shift computation against previous article
  mentioning the same entity.
- Seed record (shift_value=0) when no previous article exists.
- Skip conditions: terminal / merged / missing article_id / missing
  sentiment_score / missing entities / empty canonical_name.
- Multiple entities trigger one save_shift per entity.
- Failure isolation: repo errors mark degraded_fields without blocking.
- No LLM is invoked (pure computation node).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.sentiment_tracker import (
    SentimentTrackerNode,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/article-x",
        title="Company X announces breakthrough",
        body="Body content here.",
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_shift_repo():
    """Mock AnalyticsStorage — only the methods SentimentTrackerNode uses."""
    repo = AsyncMock()
    repo.get_last_article_shift = AsyncMock(return_value=None)
    repo.save_shift = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def base_state(sample_raw):
    """Pipeline state with article_id, sentiment, and entities populated."""
    state = PipelineState(raw=sample_raw)
    state["article_id"] = str(uuid.uuid4())
    state["sentiment"] = {
        "sentiment": "positive",
        "sentiment_score": 0.72,
    }
    state["entities"] = [
        {"canonical_name": "Company X", "type": "组织机构"},
        {"canonical_name": "Investor Y", "type": "组织机构"},
    ]
    return state


class TestSentimentTrackerNodeBasic:
    """Basic functionality — shift computation and seed records."""

    @pytest.mark.asyncio
    async def test_computes_shift_when_previous_record_exists(self, mock_shift_repo, base_state):
        """Shift value = current_sentiment - previous_after_avg."""
        mock_shift_repo.get_last_article_shift.return_value = {
            "article_id": uuid.uuid4(),
            "entity_name": "Company X",
            "shift_value": 0.10,
            "before_avg": 0.50,
            "after_avg": 0.60,  # previous article sentiment
            "detected_at": "2026-07-16T10:00:00+00:00",
        }

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        # Two entities → two save_shift calls
        assert mock_shift_repo.save_shift.await_count == 2

        # First call is for "Company X" (has previous record)
        first_call = mock_shift_repo.save_shift.await_args_list[0]
        shift_data = first_call.args[0]
        assert shift_data["entity_name"] == "Company X"
        assert shift_data["article_id"] == base_state["article_id"]
        # 0.72 - 0.60 = 0.12
        assert shift_data["shift_value"] == pytest.approx(0.12)
        assert shift_data["before_avg"] == pytest.approx(0.60)
        assert shift_data["after_avg"] == pytest.approx(0.72)
        assert shift_data["direction"] == "up"
        assert shift_data["magnitude"] == pytest.approx(0.12)
        assert shift_data["shift_type"] == "mean_shift"
        assert shift_data["community_id"] == "Company X"

        # No degraded fields on success
        assert "sentiment_shift" not in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_seeds_record_when_no_previous(self, mock_shift_repo, base_state):
        """When no previous article-level shift exists, seed with shift_value=0.

        The seed record uses before_avg=after_avg=current_sentiment so the
        next article can compute its shift against this seed.
        """
        mock_shift_repo.get_last_article_shift.return_value = None

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        assert mock_shift_repo.save_shift.await_count == 2
        first_call = mock_shift_repo.save_shift.await_args_list[0]
        shift_data = first_call.args[0]
        assert shift_data["entity_name"] == "Company X"
        assert shift_data["shift_value"] == pytest.approx(0.0)
        assert shift_data["before_avg"] == pytest.approx(0.72)
        assert shift_data["after_avg"] == pytest.approx(0.72)
        assert shift_data["direction"] == "stable"
        assert shift_data["magnitude"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_negative_shift_direction_down(self, mock_shift_repo, base_state):
        """Shift value < 0 → direction='down'."""
        base_state["sentiment"]["sentiment_score"] = 0.40
        mock_shift_repo.get_last_article_shift.return_value = {
            "article_id": uuid.uuid4(),
            "entity_name": "Company X",
            "shift_value": 0.20,
            "before_avg": 0.50,
            "after_avg": 0.70,
            "detected_at": "2026-07-16T10:00:00+00:00",
        }

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        await node.execute(base_state)

        first_call = mock_shift_repo.save_shift.await_args_list[0]
        shift_data = first_call.args[0]
        # 0.40 - 0.70 = -0.30
        assert shift_data["shift_value"] == pytest.approx(-0.30)
        assert shift_data["direction"] == "down"
        assert shift_data["magnitude"] == pytest.approx(0.30)

    @pytest.mark.asyncio
    async def test_no_llm_invocation(self, mock_shift_repo, base_state):
        """SentimentTrackerNode must not call any LLM — pure computation."""
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        # The node has no LLM dependency at all; verify by attribute absence.
        assert not hasattr(node, "_llm")
        assert not hasattr(node, "_budget")
        assert not hasattr(node, "_prompt_loader")


class TestSentimentTrackerNodeSkipConditions:
    """Skip conditions — node returns state unchanged."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, mock_shift_repo, base_state):
        base_state["terminal"] = True
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.get_last_article_shift.assert_not_called()
        mock_shift_repo.save_shift.assert_not_called()
        assert result is base_state

    @pytest.mark.asyncio
    async def test_skips_merged_state(self, mock_shift_repo, base_state):
        base_state["is_merged"] = True
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.get_last_article_shift.assert_not_called()
        mock_shift_repo.save_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_article_id_missing(self, mock_shift_repo, base_state):
        del base_state["article_id"]
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.save_shift.assert_not_called()
        assert "sentiment_shift" not in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_skips_when_sentiment_score_missing(self, mock_shift_repo, base_state):
        del base_state["sentiment"]["sentiment_score"]
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.save_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_sentiment_dict_missing(self, mock_shift_repo, base_state):
        del base_state["sentiment"]
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.save_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_entities_empty(self, mock_shift_repo, base_state):
        base_state["entities"] = []
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.save_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_entity_with_empty_canonical_name(self, mock_shift_repo, base_state):
        """Entities missing canonical_name should be skipped, others processed."""
        base_state["entities"] = [
            {"canonical_name": "", "type": "组织机构"},
            {"canonical_name": None, "type": "组织机构"},
            {"canonical_name": "Company X", "type": "组织机构"},
        ]
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        await node.execute(base_state)

        # Only one valid entity → one save_shift call
        assert mock_shift_repo.save_shift.await_count == 1
        shift_data = mock_shift_repo.save_shift.await_args.args[0]
        assert shift_data["entity_name"] == "Company X"


class TestSentimentTrackerNodeFailureIsolation:
    """Failure isolation — repo errors degrade, do not block pipeline."""

    @pytest.mark.asyncio
    async def test_get_last_article_shift_failure_degrades(self, mock_shift_repo, base_state):
        """get_last_article_shift error → degraded_fields, no save_shift."""
        mock_shift_repo.get_last_article_shift.side_effect = RuntimeError("DB connection lost")

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        mock_shift_repo.save_shift.assert_not_called()
        assert "sentiment_shift" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_save_shift_failure_degrades(self, mock_shift_repo, base_state):
        """save_shift error → degraded_fields, pipeline continues."""
        mock_shift_repo.save_shift.side_effect = RuntimeError("write failed")

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        assert "sentiment_shift" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_one_entity_failure_does_not_block_others(self, mock_shift_repo, base_state):
        """If save_shift fails for entity A, entity B is still attempted."""
        # First call to save_shift fails, second succeeds
        mock_shift_repo.save_shift.side_effect = [
            RuntimeError("first write failed"),
            None,
        ]

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)

        # Both entities were attempted
        assert mock_shift_repo.save_shift.await_count == 2
        # Degraded field is set (at least one failure)
        assert "sentiment_shift" in result.get("degraded_fields", [])


class TestSentimentTrackerNodeEdgeCases:
    """Edge cases — state integrity and field mapping."""

    @pytest.mark.asyncio
    async def test_state_returned_is_same_object(self, mock_shift_repo, base_state):
        """execute must return the same state object (in-place update)."""
        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        result = await node.execute(base_state)
        assert result is base_state

    @pytest.mark.asyncio
    async def test_shift_record_includes_required_community_fields(
        self, mock_shift_repo, base_state
    ):
        """Each shift record must populate NOT NULL community_id/shift_type/
        direction/magnitude/confidence/detected_at/window_start/window_end
        (existing schema) plus article_id/entity_name/shift_value (migration 30).
        """
        mock_shift_repo.get_last_article_shift.return_value = None

        node = SentimentTrackerNode(shift_repo=mock_shift_repo)
        await node.execute(base_state)

        # Use the first save_shift call (Company X) — await_args returns the last.
        shift_data = mock_shift_repo.save_shift.await_args_list[0].args[0]
        # Existing NOT NULL fields
        assert shift_data["community_id"] == "Company X"
        assert shift_data["shift_type"] == "mean_shift"
        assert shift_data["direction"] == "stable"
        assert shift_data["magnitude"] is not None
        assert shift_data["confidence"] is not None
        assert shift_data["detected_at"] is not None
        assert shift_data["window_start"] is not None
        assert shift_data["window_end"] is not None
        # Migration 30 fields
        assert shift_data["article_id"] == base_state["article_id"]
        assert shift_data["entity_name"] == "Company X"
        assert shift_data["shift_value"] is not None
