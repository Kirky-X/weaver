# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Pipeline graph."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db import PersistStatus
from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.graph import PHASE1_STAGES, PHASE3_STAGES, Pipeline
from modules.processing.pipeline.state import PipelineState
from tests.unit.modules.pipeline.conftest import make_pipeline


class TestPipelineConstants:
    """Test pipeline constants."""

    def test_phase1_stages_defined(self):
        """Test PHASE1_STAGES is defined."""
        assert PHASE1_STAGES is not None
        assert "classifier" in PHASE1_STAGES
        assert "cleaner" in PHASE1_STAGES
        assert "categorizer" in PHASE1_STAGES
        assert "vectorize" in PHASE1_STAGES

    def test_phase3_stages_defined(self):
        """Test PHASE3_STAGES is defined."""
        assert PHASE3_STAGES is not None
        assert "re_vectorize" in PHASE3_STAGES
        assert "analyze" in PHASE3_STAGES
        assert "credibility" in PHASE3_STAGES
        assert "entity_extractor" in PHASE3_STAGES


class TestPipelineInit:
    """Test Pipeline initialization."""

    def test_init_basic(self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus):
        """Test basic initialization."""
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        assert pipeline._accepting is True
        assert pipeline._phase1_concurrency == 5
        assert pipeline._phase3_concurrency == 5

    def test_init_custom_concurrency(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test initialization with custom concurrency from settings."""
        from modules.processing.pipeline.config import PhaseConfig, PipelineSettings

        mock_settings = MagicMock()
        mock_settings.pipeline = PipelineSettings(
            phase1=PhaseConfig(concurrency=5),
            phase3=PhaseConfig(concurrency=3),
        )
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            settings=mock_settings,
            spacy=MagicMock(),
        )

        assert pipeline._phase1_concurrency == 5
        assert pipeline._phase3_concurrency == 3

    def test_init_with_optional_deps(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test initialization with optional dependencies."""
        mock_spacy = MagicMock()
        mock_vector_repo = MagicMock()
        mock_article_repo = MagicMock()
        mock_neo4j_writer = MagicMock()
        mock_source_auth_repo = MagicMock()

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            spacy=mock_spacy,
            vector_repo=mock_vector_repo,
            article_repo=mock_article_repo,
            graph_writer=mock_neo4j_writer,
            source_auth_repo=mock_source_auth_repo,
        )

        assert pipeline._deps.repos.article_repo == mock_article_repo
        assert pipeline._deps.repos.graph_writer == mock_neo4j_writer

    def test_default_concurrency_values(self):
        """Test default concurrency values fall back to TOML default."""
        pipeline = make_pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )
        assert pipeline._phase1_concurrency == 5
        assert pipeline._phase3_concurrency == 5


class TestPipelineStopAccepting:
    """Test stop_accepting method."""

    @pytest.fixture
    def pipeline(self):
        """Create Pipeline instance."""
        return make_pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_stop_accepting(self, pipeline):
        """Test stop_accepting sets flag."""
        assert pipeline._accepting is True
        await pipeline.stop_accepting()
        assert pipeline._accepting is False


class TestPipelineDrain:
    """Test drain method."""

    @pytest.fixture
    def pipeline(self):
        """Create Pipeline instance."""
        return make_pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_drain(self, pipeline):
        """Test drain completes without error."""
        await pipeline.drain()


@pytest.mark.filterwarnings("ignore::DeprecationWarning:torch.jit")
class TestPipelineProcessBatch:
    """Test process_batch method."""

    @pytest.fixture
    def mock_llm_for_batch(self):
        """Mock LLM client with complex call_at behavior for batch tests."""
        from core.llm import CallPoint

        llm = MagicMock()

        def mock_call(call_point, data, output_model=None):
            if call_point == CallPoint.CLASSIFIER:
                return MagicMock(is_news=True, confidence=0.95)
            elif call_point == CallPoint.CLEANER:
                return MagicMock(cleaned_title="Cleaned Title", cleaned_body="Cleaned Body")
            elif call_point == CallPoint.CATEGORIZER:
                return MagicMock(category="科技", language="zh", region="中国")
            elif call_point == CallPoint.ANALYZE:
                return MagicMock(
                    summary="Summary",
                    event_time=None,
                    subjects=[],
                    key_data=[],
                    impact="Impact",
                    has_data=False,
                    sentiment="neutral",
                    sentiment_score=0.5,
                    primary_emotion="平静",
                    emotion_targets=[],
                    score=0.7,
                )
            elif call_point == CallPoint.CREDIBILITY_CHECKER:
                return MagicMock(score=0.8, flags=[])
            elif call_point == CallPoint.ENTITY_EXTRACTOR:
                return MagicMock(entities=[], relations=[])
            elif call_point == CallPoint.MERGER:
                return MagicMock(merged_title="Merged Title", merged_body="Merged Body")
            return MagicMock()

        llm.call_at = AsyncMock(side_effect=mock_call)

        def mock_embed(texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]

        llm.embed_default = AsyncMock(side_effect=mock_embed)
        return llm

    @pytest.fixture
    def mock_budget_for_batch(self):
        """Mock token budget manager for batch tests."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader_for_batch(self):
        """Mock prompt loader for batch tests."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_event_bus_for_batch(self):
        """Mock event bus for batch tests."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_source_auth_repo_for_batch(self):
        """Mock source authority repo for batch tests."""
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.8))
        return repo

    @pytest.fixture
    def pipeline_for_batch(
        self,
        mock_llm_for_batch,
        mock_budget_for_batch,
        mock_prompt_loader_for_batch,
        mock_event_bus_for_batch,
        mock_source_auth_repo_for_batch,
    ):
        """Create Pipeline instance with mocks for batch tests."""
        return make_pipeline(
            llm=mock_llm_for_batch,
            budget=mock_budget_for_batch,
            prompt_loader=mock_prompt_loader_for_batch,
            event_bus=mock_event_bus_for_batch,
            source_auth_repo=mock_source_auth_repo_for_batch,
        )

    @pytest.fixture
    def sample_article_raw_for_batch(self):
        """Create sample RawArticle for batch tests."""
        return RawArticle(
            url="https://example.com/test-article",
            title="Test Article Title",
            body="Test article body content for processing.",
            source="test_source",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_process_batch_not_accepting(
        self, pipeline_for_batch, sample_article_raw_for_batch
    ):
        """Test process_batch raises when not accepting."""
        await pipeline_for_batch.stop_accepting()

        with pytest.raises(RuntimeError, match="not accepting"):
            await pipeline_for_batch.process_batch([sample_article_raw_for_batch])

    @pytest.mark.asyncio
    async def test_process_batch_single_article(
        self, pipeline_for_batch, sample_article_raw_for_batch
    ):
        """Test processing a single article."""
        results = await pipeline_for_batch.process_batch([sample_article_raw_for_batch])

        assert len(results) == 1
        assert "raw" in results[0]

    @pytest.mark.asyncio
    async def test_process_batch_multiple_articles(self, pipeline_for_batch):
        """Test processing multiple articles."""
        articles = [
            RawArticle(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}",
                source="test",
                source_host="example.com",
            )
            for i in range(3)
        ]

        results = await pipeline_for_batch.process_batch(articles)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_process_batch_empty(self, pipeline_for_batch):
        """Test processing empty batch."""
        results = await pipeline_for_batch.process_batch([])

        assert len(results) == 0


class TestPipelinePhase1:
    """Test _phase1_per_article method."""

    @pytest.fixture
    def mock_llm_for_phase1(self):
        """Mock LLM client for phase1 tests."""
        from core.llm import CallPoint

        llm = MagicMock()

        def mock_call(call_point, data, output_model=None):
            if call_point == CallPoint.CLASSIFIER:
                return MagicMock(is_news=True, confidence=0.95)
            elif call_point == CallPoint.CLEANER:
                return MagicMock(cleaned_title="Title", cleaned_body="Body")
            elif call_point == CallPoint.CATEGORIZER:
                return MagicMock(category="科技", language="zh", region="中国")
            return MagicMock()

        llm.call_at = AsyncMock(side_effect=mock_call)

        def mock_embed(texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]

        llm.embed_default = AsyncMock(side_effect=mock_embed)
        return llm

    @pytest.fixture
    def mock_budget_for_phase1(self):
        """Mock token budget manager for phase1 tests."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader_for_phase1(self):
        """Mock prompt loader for phase1 tests."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def pipeline_for_phase1(
        self, mock_llm_for_phase1, mock_budget_for_phase1, mock_prompt_loader_for_phase1
    ):
        """Create Pipeline instance for phase1 tests."""
        return make_pipeline(
            llm=mock_llm_for_phase1,
            budget=mock_budget_for_phase1,
            prompt_loader=mock_prompt_loader_for_phase1,
            event_bus=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_phase1_processes_all_nodes(self, pipeline_for_phase1):
        """Test phase1 processes classifier, cleaner, categorizer, vectorize."""
        raw = MagicMock()
        raw.title = (
            "重大新闻突发事件报道"  # Title with enough news keywords to pass rule classifier
        )
        raw.body = "Body content for the article"
        raw.url = "https://news.example.com/breaking-news"
        raw.source_host = "example.com"
        raw.publish_time = None

        state = PipelineState(raw=raw)
        result = await pipeline_for_phase1._phase1_per_article(state, [])

        assert "is_news" in result
        assert "cleaned" in result
        assert "category" in result
        assert "vectors" in result

    @pytest.mark.asyncio
    async def test_phase1_stops_on_terminal_after_classifier(self, pipeline_for_phase1):
        """Test phase1 processes classifier then stops when terminal is set."""
        raw = MagicMock()
        raw.title = "Test"  # len < 5 → rule classifier returns False → terminal=True
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"
        raw.publish_time = None

        state = PipelineState(raw=raw)

        result = await pipeline_for_phase1._phase1_per_article(state, [])

        # Rule classifier marks short titles as non-news → terminal=True
        assert result.get("is_news") is False
        assert result.get("terminal") is True
        # Cleaner should NOT run when terminal
        assert result.get("cleaned") is None


class TestPipelinePhase3:
    """Test _phase3_per_article method."""

    @pytest.fixture
    def mock_llm_for_phase3(self):
        """Mock LLM client for phase3 tests."""
        from core.llm import CallPoint

        llm = MagicMock()

        def mock_call(call_point, data, output_model=None):
            if call_point == CallPoint.ANALYZE:
                return MagicMock(
                    summary="Summary",
                    event_time=None,
                    subjects=[],
                    key_data=[],
                    impact="Impact",
                    has_data=False,
                    sentiment="neutral",
                    sentiment_score=0.5,
                    primary_emotion="平静",
                    emotion_targets=[],
                    score=0.7,
                )
            elif call_point == CallPoint.CREDIBILITY_CHECKER:
                return MagicMock(score=0.8, flags=[])
            elif call_point == CallPoint.ENTITY_EXTRACTOR:
                return MagicMock(entities=[], relations=[])
            return MagicMock()

        llm.call_at = AsyncMock(side_effect=mock_call)

        def mock_embed(texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]

        llm.embed_default = AsyncMock(side_effect=mock_embed)
        return llm

    @pytest.fixture
    def mock_budget_for_phase3(self):
        """Mock token budget manager for phase3 tests."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader_for_phase3(self):
        """Mock prompt loader for phase3 tests."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_event_bus_for_phase3(self):
        """Mock event bus for phase3 tests."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_source_auth_repo_for_phase3(self):
        """Mock source authority repo for phase3 tests."""
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.8))
        return repo

    @pytest.fixture
    def pipeline_for_phase3(
        self,
        mock_llm_for_phase3,
        mock_budget_for_phase3,
        mock_prompt_loader_for_phase3,
        mock_event_bus_for_phase3,
        mock_source_auth_repo_for_phase3,
    ):
        """Create Pipeline instance for phase3 tests."""
        return make_pipeline(
            llm=mock_llm_for_phase3,
            budget=mock_budget_for_phase3,
            prompt_loader=mock_prompt_loader_for_phase3,
            event_bus=mock_event_bus_for_phase3,
            source_auth_repo=mock_source_auth_repo_for_phase3,
        )

    @pytest.mark.asyncio
    async def test_phase3_processes_all_nodes(self, pipeline_for_phase3):
        """Test phase3 processes re_vectorize, analyze, credibility, entity_extractor."""
        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"

        result = await pipeline_for_phase3._phase3_per_article(state, [])

        assert "vectors" in result
        assert "summary_info" in result
        assert "credibility" in result

    @pytest.mark.asyncio
    async def test_phase3_skips_terminal(self, pipeline_for_phase3):
        """Test phase3 skips terminal articles."""
        state = PipelineState(raw=MagicMock())
        state["terminal"] = True

        result = await pipeline_for_phase3._phase3_per_article(state, [])

        assert result.get("terminal") is True

    @pytest.mark.asyncio
    async def test_phase3_terminal_runs_enrichment_skips_revectorize(
        self,
        mock_llm_for_phase3,
        mock_budget_for_phase3,
        mock_prompt_loader_for_phase3,
        mock_event_bus_for_phase3,
        mock_source_auth_repo_for_phase3,
    ):
        """Test terminal article: re_vectorize skipped, but analyze/quality/credibility/entity run."""

        def node_execute(s):
            return dict(s)

        pipeline = make_pipeline(
            llm=mock_llm_for_phase3,
            budget=mock_budget_for_phase3,
            prompt_loader=mock_prompt_loader_for_phase3,
            event_bus=mock_event_bus_for_phase3,
            source_auth_repo=mock_source_auth_repo_for_phase3,
        )
        pipeline._re_vectorize = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._analyze = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._quality_scorer = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._credibility = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_extractor = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._deps.nlp.entity_resolver = MagicMock(execute=AsyncMock(side_effect=node_execute))

        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["terminal"] = True  # ← terminal article

        result = await pipeline._phase3_per_article(state, [])

        # re_vectorize MUST NOT be called for terminal articles
        pipeline._re_vectorize.execute.assert_not_awaited()
        # All enrichment nodes MUST be called
        pipeline._analyze.execute.assert_awaited_once()
        pipeline._quality_scorer.execute.assert_awaited_once()
        pipeline._credibility.execute.assert_awaited_once()
        pipeline._entity_extractor.execute.assert_awaited_once()
        # Terminal flag preserved in result
        assert result.get("terminal") is True

    @pytest.mark.asyncio
    async def test_phase3_non_terminal_runs_all_nodes(
        self,
        mock_llm_for_phase3,
        mock_budget_for_phase3,
        mock_prompt_loader_for_phase3,
        mock_event_bus_for_phase3,
        mock_source_auth_repo_for_phase3,
    ):
        """Test non-terminal article: all Phase 3 nodes run including re_vectorize."""

        def node_execute(s):
            return dict(s)

        pipeline = make_pipeline(
            llm=mock_llm_for_phase3,
            budget=mock_budget_for_phase3,
            prompt_loader=mock_prompt_loader_for_phase3,
            event_bus=mock_event_bus_for_phase3,
            source_auth_repo=mock_source_auth_repo_for_phase3,
        )
        pipeline._re_vectorize = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._analyze = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._quality_scorer = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._credibility = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_extractor = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._deps.nlp.entity_resolver = MagicMock(execute=AsyncMock(side_effect=node_execute))

        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        # terminal=False (default)

        await pipeline._phase3_per_article(state, [])

        # All nodes MUST be called including re_vectorize
        pipeline._re_vectorize.execute.assert_awaited_once()
        pipeline._analyze.execute.assert_awaited_once()
        pipeline._quality_scorer.execute.assert_awaited_once()
        pipeline._credibility.execute.assert_awaited_once()
        pipeline._entity_extractor.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase3_skips_merged(self, pipeline_for_phase3):
        """Test phase3 skips merged articles."""
        state = PipelineState(raw=MagicMock())
        state["is_merged"] = True

        result = await pipeline_for_phase3._phase3_per_article(state, [])

        assert result.get("is_merged") is True


class TestPipelineUpdateProcessingStage:
    """Test _update_processing_stage method."""

    @pytest.fixture
    def pipeline_no_repo(self):
        """Create Pipeline without article_repo."""
        return make_pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )

    @pytest.fixture
    def pipeline_with_repo(self):
        """Create Pipeline with article_repo."""
        return make_pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
            article_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_update_stage_no_repo(self, pipeline_no_repo):
        """Test update stage without article_repo."""
        state = PipelineState(raw=MagicMock())
        state["article_id"] = "test-id"

        await pipeline_no_repo._update_processing_stage(state, "test_stage", [])

    @pytest.mark.asyncio
    async def test_update_stage_no_article_id(self, pipeline_with_repo):
        """Test update stage without article_id."""
        state = PipelineState(raw=MagicMock())

        await pipeline_with_repo._update_processing_stage(state, "test_stage", [])

    @pytest.mark.asyncio
    async def test_update_stage_success(self, pipeline_with_repo):
        """Test successful update of processing stage."""
        import uuid

        article_id = uuid.uuid4()

        state = PipelineState(raw=MagicMock())
        state["article_id"] = str(article_id)

        pending_updates: list[tuple[str, str]] = []
        await pipeline_with_repo._update_processing_stage(
            state, "phase1_classifier", pending_updates
        )

        # _update_processing_stage now collects updates in the passed list
        assert len(pending_updates) == 1
        assert pending_updates[0] == (
            str(article_id),
            "phase1_classifier",
        )


class TestPipelinePersistBatch:
    """Test _persist_batch method."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        return MagicMock()

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        return MagicMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        return MagicMock()

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_persist_batch_empty_list(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch with empty list."""
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        await pipeline._persist_batch([], 0, 0, 0)

    @pytest.mark.asyncio
    async def test_persist_batch_all_terminal(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch skips all terminal articles."""
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        states = [PipelineState(raw=MagicMock()) for _ in range(3)]
        for state in states:
            state["terminal"] = True

        await pipeline._persist_batch(states, len(states), 0, 0)

    @pytest.mark.asyncio
    async def test_persist_batch_with_article_repo(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch with article_repo."""
        import uuid

        article_ids = [uuid.uuid4() for _ in range(2)]
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=article_ids)

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        states = [PipelineState(raw=raw) for _ in range(2)]
        for state in states:
            state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist_batch(states, len(states), 0, 0)

        mock_article_repo.bulk_upsert.assert_called_once()
        for state in states:
            assert "article_id" in state

    @pytest.mark.asyncio
    async def test_persist_batch_with_vectors(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch with vector persistence."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])

        mock_vector_repo = MagicMock()
        mock_vector_repo.bulk_upsert_article_vectors = AsyncMock(return_value=1)

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
            vector_repo=mock_vector_repo,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["vectors"] = {
            "title": [0.1] * 1024,
            "content": [0.2] * 1024,
            "model_id": "test-model",
        }

        await pipeline._persist_batch([state], 1, 0, 0)

        mock_vector_repo.bulk_upsert_article_vectors.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_with_neo4j(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch with Neo4j persistence."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])
        mock_article_repo.update_persist_status = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(return_value=["entity1"])

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
            graph_writer=mock_neo4j_writer,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist_batch([state], 1, 0, 0)

        mock_neo4j_writer.write.assert_called_once()
        assert "neo4j_ids" in state

    @pytest.mark.asyncio
    async def test_persist_batch_handles_pg_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch handles PostgreSQL errors."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(side_effect=Exception("PG error"))
        mock_article_repo.mark_failed = AsyncMock()

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["article_id"] = str(article_id)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist_batch([state], 1, 0, 0)

    @pytest.mark.asyncio
    async def test_persist_batch_handles_neo4j_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch handles Neo4j errors."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(side_effect=Exception("Neo4j error"))

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
            graph_writer=mock_neo4j_writer,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist_batch([state], 1, 0, 0)

        mock_article_repo.mark_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_batch_graph_writer_none_logs_error_not_silent(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """REM-005: When graph_writer is None, persist_batch must log ERROR (not silent).

        Root cause: graph_writer None was treated as "PG success counts as complete",
        silently incrementing batch_completed without writing to graph. This causes
        articles to be stuck in PG_DONE forever (graph sync never happens).
        Fix: Log ERROR and do NOT increment batch_completed so articles remain
        in PG_DONE for retry_neo4j_writes to pick up.
        """
        import uuid
        from unittest.mock import patch

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])

        # graph_writer is None (LadybugDB unavailable)
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
            graph_writer=None,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        # Suggestion 5: Verify log.error is actually called (not just silent).
        with patch("modules.processing.pipeline.persistence.log") as mock_log:
            completed, failed = await pipeline._persist_batch([state], 1, 0, 0)

            # REM-005: batch_completed must NOT be incremented when graph_writer is None
            assert completed == 0
            assert failed == 0
            # Suggestion 5: log.error must be called for each article
            assert mock_log.error.called
            error_call_args = mock_log.error.call_args
            assert "graph_writer_unavailable" in str(error_call_args) or any(
                "graph_writer" in str(arg) for arg in error_call_args.args
            )

    @pytest.mark.asyncio
    async def test_persist_batch_graph_batch_error_marks_failed(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """REM-005: Batch write errors must trigger mark_failed (not just log).

        Root cause: _persist_to_graph_batch only logged errors and incremented
        batch_failed, but did NOT call mark_failed. Articles stayed in PG_DONE
        status, appearing "stuck" rather than "failed".
        Fix: Call mark_failed for each article in the errors list.
        """
        import uuid

        article_id = uuid.uuid4()
        article_id_str = str(article_id)
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=[article_id])
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.done_status = PersistStatus.NEO4J_DONE
        # write_batch returns errors but no article_ids
        mock_neo4j_writer.write_batch = AsyncMock(
            return_value={
                "article_ids": [],
                "neo4j_ids": [],
                "errors": [(article_id_str, "LadybugDB write failed")],
            }
        )

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
            graph_writer=mock_neo4j_writer,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id_str
        state["cleaned"] = {"title": "Title", "body": "Body"}

        completed, failed = await pipeline._persist_batch([state], 1, 0, 0)

        # batch_failed should be incremented
        assert failed == 1
        # REM-005: mark_failed must be called for the failed article
        mock_article_repo.mark_failed.assert_awaited_once()
        mark_failed_args = mock_article_repo.mark_failed.call_args
        # First positional arg should be the article UUID
        assert mark_failed_args.args[0] == article_id


class TestPipelineCommunityUpdate:
    """Test _maybe_trigger_community_update method."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        return MagicMock()

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        return MagicMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        return MagicMock()

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_community_update_no_updater(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update without updater."""
        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        raw = MagicMock()
        state = PipelineState(raw=raw)
        state["entities"] = [{"name": "Entity1"}]

        await pipeline._maybe_trigger_community_update([state])

    @pytest.mark.asyncio
    async def test_community_update_no_entities(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update without entities."""
        mock_updater = MagicMock()
        mock_updater.get_stats = AsyncMock(
            return_value=MagicMock(pending_entity_count=0, last_incremental_update_at=None)
        )

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            community_updater=mock_updater,
        )

        raw = MagicMock()
        state = PipelineState(raw=raw)

        await pipeline._maybe_trigger_community_update([state])

        mock_updater.get_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_community_update_triggers(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update triggers when conditions met."""
        from dataclasses import dataclass

        @dataclass
        class UpdateResult:
            affected_communities: int
            entities_reassigned: int
            duration_seconds: float

        mock_updater = MagicMock()
        mock_updater.get_stats = AsyncMock(
            return_value=MagicMock(pending_entity_count=10, last_incremental_update_at=None)
        )
        mock_updater.should_trigger = AsyncMock(return_value=True)
        mock_updater.run_incremental_update = AsyncMock(
            return_value=UpdateResult(
                affected_communities=5, entities_reassigned=3, duration_seconds=1.5
            )
        )

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            community_updater=mock_updater,
        )

        raw = MagicMock()
        state = PipelineState(raw=raw)
        state["entities"] = [{"canonical_name": "Entity1"}, {"name": "Entity2"}]

        await pipeline._maybe_trigger_community_update([state])

        mock_updater.run_incremental_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_community_update_increments_pending(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update increments pending when not triggered."""
        mock_updater = MagicMock()
        mock_updater.get_stats = AsyncMock(
            return_value=MagicMock(pending_entity_count=5, last_incremental_update_at=None)
        )
        mock_updater.should_trigger = AsyncMock(return_value=False)
        mock_updater.increment_pending_count = AsyncMock()

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            community_updater=mock_updater,
        )

        raw = MagicMock()
        state = PipelineState(raw=raw)
        state["entities"] = [{"canonical_name": "Entity1"}]

        await pipeline._maybe_trigger_community_update([state])

        mock_updater.increment_pending_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_community_update_handles_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update handles errors gracefully."""
        mock_updater = MagicMock()
        mock_updater.get_stats = AsyncMock(side_effect=Exception("Update error"))

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            community_updater=mock_updater,
        )

        raw = MagicMock()
        state = PipelineState(raw=raw)
        state["entities"] = [{"name": "Entity1"}]

        # Should not raise
        await pipeline._maybe_trigger_community_update([state])

    @pytest.mark.asyncio
    async def test_community_update_entity_with_attrs(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test community update extracts entity names from objects with attributes."""
        mock_updater = MagicMock()
        mock_updater.get_stats = AsyncMock(
            return_value=MagicMock(pending_entity_count=0, last_incremental_update_at=None)
        )
        mock_updater.should_trigger = AsyncMock(return_value=True)

        from dataclasses import dataclass

        @dataclass
        class UpdateResult:
            affected_communities: int
            entities_reassigned: int
            duration_seconds: float

        mock_updater.run_incremental_update = AsyncMock(
            return_value=UpdateResult(
                affected_communities=1, entities_reassigned=0, duration_seconds=0.5
            )
        )

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            community_updater=mock_updater,
        )

        raw = MagicMock()

        # Entity with canonical_name attribute
        class MockEntity:
            canonical_name = "TestEntity"

        state = PipelineState(raw=raw)
        state["entities"] = [MockEntity()]

        await pipeline._maybe_trigger_community_update([state])

        mock_updater.run_incremental_update.assert_called_once()


class TestPipelineGraphDoneStatus:
    """Tests for graph_writer.done_status property (spec: pipeline-status-dynamic).

    Verifies that persist_status is dynamically selected based on
    graph_writer type: LadybugWriter → LADYBUG_DONE, Neo4jWriter → NEO4J_DONE.
    """

    @pytest.fixture
    def mock_llm(self):
        return AsyncMock()

    @pytest.fixture
    def mock_budget(self):
        return MagicMock()

    @pytest.fixture
    def mock_prompt_loader(self):
        return MagicMock()

    @pytest.fixture
    def mock_event_bus(self):
        return MagicMock()

    def test_ladybug_writer_returns_ladybug_done(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Scenario: Pipeline with LadybugWriter → LADYBUG_DONE."""
        from modules.storage.ladybug.writer import LadybugWriter

        mock_pool = MagicMock()
        ladybug_writer = LadybugWriter(mock_pool)

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            graph_writer=ladybug_writer,
        )

        assert pipeline._deps.repos.graph_writer.done_status == PersistStatus.LADYBUG_DONE

    def test_neo4j_writer_returns_neo4j_done(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Scenario: Pipeline with Neo4jWriter → NEO4J_DONE."""
        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.done_status = PersistStatus.NEO4J_DONE

        pipeline = make_pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            graph_writer=mock_neo4j_writer,
        )

        assert pipeline._deps.repos.graph_writer.done_status == PersistStatus.NEO4J_DONE
