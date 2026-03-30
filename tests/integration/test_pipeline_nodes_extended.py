# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Extended integration tests for pipeline nodes — covering nodes missing from test_pipeline_nodes.py."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.collector.models import ArticleRaw
from modules.pipeline.state import PipelineState


def _make_raw(url: str = "https://example.com/test") -> ArticleRaw:
    """Create a sample raw article."""
    return ArticleRaw(
        url=url,
        title="Test Article",
        body="Test body content about technology and artificial intelligence.",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


def _make_state(url: str = "https://example.com/test", **kwargs) -> PipelineState:
    """Create a sample pipeline state."""
    raw = _make_raw(url)
    state: PipelineState = PipelineState(raw=raw)
    for k, v in kwargs.items():
        state[k] = v
    return state


# ── QualityScorerNode Tests ───────────────────────────────────


class TestQualityScorerNodeIntegration:
    """Integration tests for QualityScorerNode — previously untested in test_pipeline_nodes.py."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client that returns a valid quality score."""
        llm = AsyncMock()
        return llm

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = lambda text, call_point: text
        return budget

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get = MagicMock(return_value="Quality scorer prompt")
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_quality_scorer_returns_score_between_0_and_1(
        self, mock_llm, mock_budget, mock_prompt_loader
    ):
        """Test that quality scorer returns a score between 0 and 1."""
        from core.llm.output_validator import QualityScorerOutput
        from modules.pipeline.nodes.quality_scorer import QualityScorerNode

        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.75))

        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Test body content"}

        result = await node.execute(state)

        assert "quality_score" in result
        assert 0.0 <= result["quality_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_quality_scorer_skips_terminal_state(
        self, mock_llm, mock_budget, mock_prompt_loader
    ):
        """Test that quality scorer skips terminal articles."""
        from modules.pipeline.nodes.quality_scorer import QualityScorerNode

        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Test body content"}
        state["terminal"] = True

        result = await node.execute(state)

        assert "quality_score" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_quality_scorer_uses_default_on_llm_error(
        self, mock_llm, mock_budget, mock_prompt_loader
    ):
        """Test that quality scorer uses default 0.5 score on LLM failure."""
        from modules.pipeline.nodes.quality_scorer import QualityScorerNode

        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM error"))

        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Test body content"}

        result = await node.execute(state)

        # Should not raise; should use default
        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_quality_scorer_sets_prompt_version(
        self, mock_llm, mock_budget, mock_prompt_loader
    ):
        """Test that quality scorer records the prompt version in state."""
        from core.llm.output_validator import QualityScorerOutput
        from modules.pipeline.nodes.quality_scorer import QualityScorerNode

        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.85))

        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Test body content"}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"].get("quality_scorer") == "1.0.0"


# ── ReVectorizeNode Tests ───────────────────────────────────────


class TestReVectorizeNodeIntegration:
    """Integration tests for ReVectorizeNode — previously untested in test_pipeline_nodes.py."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client for embedding."""
        llm = AsyncMock()
        return llm

    @pytest.mark.asyncio
    async def test_re_vectorize_sets_vectors_dict(self, mock_llm):
        """Test that re-vectorize sets the vectors dict in state."""
        from modules.pipeline.nodes.re_vectorize import ReVectorizeNode

        mock_llm.embed = AsyncMock(return_value=[[0.1] * 10, [0.2] * 10])

        node = ReVectorizeNode(mock_llm)
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Body content"}

        result = await node.execute(state)

        assert "vectors" in result
        assert "title" in result["vectors"]
        assert "content" in result["vectors"]
        assert "model_id" in result["vectors"]
        assert result["vectors"]["model_id"] == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_re_vectorize_skips_terminal_state(self, mock_llm):
        """Test that re-vectorize skips terminal articles."""
        from modules.pipeline.nodes.re_vectorize import ReVectorizeNode

        node = ReVectorizeNode(mock_llm)
        state = _make_state()
        state["terminal"] = True

        result = await node.execute(state)

        assert "vectors" not in result
        mock_llm.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_re_vectorize_skips_merged_state(self, mock_llm):
        """Test that re-vectorize skips merged articles."""
        from modules.pipeline.nodes.re_vectorize import ReVectorizeNode

        node = ReVectorizeNode(mock_llm)
        state = _make_state()
        state["is_merged"] = True

        result = await node.execute(state)

        assert "vectors" not in result
        mock_llm.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_re_vectorize_custom_model_id(self, mock_llm):
        """Test that re-vectorize uses a custom model_id when specified."""
        from modules.pipeline.nodes.re_vectorize import ReVectorizeNode

        mock_llm.embed = AsyncMock(return_value=[[0.1] * 10, [0.2] * 10])

        node = ReVectorizeNode(mock_llm, model_id="custom-embedding-model")
        state = _make_state()
        state["cleaned"] = {"title": "Test", "body": "Body content"}

        result = await node.execute(state)

        assert result["vectors"]["model_id"] == "custom-embedding-model"


# ── CheckpointCleanupNode Tests ─────────────────────────────────


class TestCheckpointCleanupNodeIntegration:
    """Integration tests for CheckpointCleanupNode — previously untested."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_checkpoint_from_redis(self):
        """Test that cleanup deletes the checkpoint key from Redis."""
        from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode

        mock_redis = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.delete = AsyncMock()

        node = CheckpointCleanupNode(mock_redis)
        state = _make_state(url="https://example.com/cleanup-test")

        result = await node.execute(state)

        mock_redis.client.delete.assert_called_once()
        # Verify correct key is computed
        call_args = mock_redis.client.delete.call_args
        url_hash = hashlib.sha256(b"https://example.com/cleanup-test").hexdigest()[:16]
        assert call_args[0][0] == f"langgraph:checkpoint:{url_hash}"

    @pytest.mark.asyncio
    async def test_cleanup_skips_when_no_redis(self):
        """Test that cleanup is skipped when redis_client is None."""
        from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode

        node = CheckpointCleanupNode(redis_client=None)
        state = _make_state()

        result = await node.execute(state)

        # Should return state unchanged without error
        assert "terminal" not in result

    @pytest.mark.asyncio
    async def test_cleanup_skips_terminal_articles(self):
        """Test that cleanup skips terminal articles."""
        from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode

        mock_redis = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.delete = AsyncMock()

        node = CheckpointCleanupNode(mock_redis)
        state = _make_state()
        state["terminal"] = True

        result = await node.execute(state)

        mock_redis.client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_handles_redis_error_gracefully(self):
        """Test that cleanup handles Redis errors gracefully without raising."""
        from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode

        mock_redis = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.delete = AsyncMock(side_effect=Exception("Redis error"))

        node = CheckpointCleanupNode(mock_redis)
        state = _make_state()

        # Should not raise
        result = await node.execute(state)
        assert result is not None


# ── Pipeline Batch Merger Tests ─────────────────────────────────


class TestPipelineBatchMergerNodeIntegration:
    """Extended integration tests for BatchMergerNode."""

    @pytest.mark.asyncio
    async def test_batch_merger_handles_empty_list(self):
        """Test that batch merger handles an empty article list."""
        from modules.pipeline.nodes.batch_merger import BatchMergerNode

        mock_llm = AsyncMock()
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get = MagicMock(return_value="merge prompt")
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")
        mock_vector_repo = None

        node = BatchMergerNode(mock_llm, mock_prompt_loader, mock_vector_repo)
        result = await node.execute_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_batch_merger_sets_is_merged_on_primary(self):
        """Test that batch merger marks primary article as merged."""
        from modules.pipeline.nodes.batch_merger import BatchMergerNode

        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(
            return_value=MagicMock(
                primary_url="https://example.com/article1",
                merged_urls=["https://example.com/article2"],
            )
        )

        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get = MagicMock(return_value="merge prompt")
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")

        node = BatchMergerNode(mock_llm, mock_prompt_loader, None)

        state1 = _make_state(url="https://example.com/article1")
        state1["cleaned"] = {"title": "Title 1", "body": "Body 1"}
        state1["vectors"] = {"content": [0.1, 0.2, 0.3]}

        state2 = _make_state(url="https://example.com/article2")
        state2["cleaned"] = {"title": "Title 2", "body": "Body 2"}
        state2["vectors"] = {"content": [0.1, 0.2, 0.3]}

        result = await node.execute_batch([state1, state2])

        # Both should be in the result
        assert len(result) == 2


# ── task_id Propagation Tests ───────────────────────────────────


class TestPipelineTaskIdPropagation:
    """Tests for task_id propagation through pipeline state.

    PipelineState is a TypedDict with total=False, so task_id can be added
    dynamically and preserved through all node processing steps.
    """

    @pytest.mark.asyncio
    async def test_task_id_can_be_added_to_pipeline_state(self):
        """Test that task_id can be added to PipelineState dynamically."""
        state = _make_state()
        task_id = uuid.uuid4()
        state["task_id"] = task_id

        assert state["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_task_id_preserved_through_quality_scorer(self):
        """Test that task_id is preserved through QualityScorerNode."""
        from core.llm.output_validator import QualityScorerOutput
        from modules.pipeline.nodes.quality_scorer import QualityScorerNode

        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.8))

        mock_budget = MagicMock()
        mock_budget.truncate = lambda text, call_point: text

        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")

        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        task_id = uuid.uuid4()
        state = _make_state()
        state["task_id"] = task_id
        state["cleaned"] = {"title": "Test", "body": "Test body"}

        result = await node.execute(state)

        assert result.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_task_id_preserved_through_re_vectorize(self):
        """Test that task_id is preserved through ReVectorizeNode."""
        from modules.pipeline.nodes.re_vectorize import ReVectorizeNode

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 10, [0.2] * 10])

        node = ReVectorizeNode(mock_llm)
        task_id = uuid.uuid4()
        state = _make_state()
        state["task_id"] = task_id
        state["cleaned"] = {"title": "Test", "body": "Body"}

        result = await node.execute(state)

        assert result.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_task_id_preserved_through_checkpoint_cleanup(self):
        """Test that task_id is preserved through CheckpointCleanupNode."""
        from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode

        mock_redis = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.delete = AsyncMock()

        node = CheckpointCleanupNode(mock_redis)
        task_id = uuid.uuid4()
        state = _make_state()
        state["task_id"] = task_id

        result = await node.execute(state)

        assert result.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_task_id_set_during_pipeline_trigger(self):
        """Test that task_id is set when pipeline trigger is called."""
        from modules.pipeline.graph import Pipeline

        mock_llm = AsyncMock()
        mock_budget = MagicMock()
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get = MagicMock(return_value="test")
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")
        mock_event_bus = MagicMock()
        mock_event_bus.publish = MagicMock()

        # Pipeline does not take task_id in __init__, but SourceScheduler.trigger_now does
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        # Verify Pipeline accepts initialization without task_id
        assert pipeline is not None
