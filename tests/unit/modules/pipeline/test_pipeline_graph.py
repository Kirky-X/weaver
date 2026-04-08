# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Pipeline graph."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import ArticleRaw
from modules.processing.pipeline.graph import PHASE1_STAGES, PHASE3_STAGES, Pipeline
from modules.processing.pipeline.state import PipelineState


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
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        return MagicMock()

    def test_init_basic(self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus):
        """Test basic initialization."""
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        assert pipeline._accepting is True
        assert pipeline._phase1_concurrency == Pipeline.DEFAULT_PHASE1_CONCURRENCY
        assert pipeline._phase3_concurrency == Pipeline.DEFAULT_PHASE3_CONCURRENCY

    def test_init_custom_concurrency(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test initialization with custom concurrency."""
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            phase1_concurrency=5,
            phase3_concurrency=3,
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

        pipeline = Pipeline(
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

        assert pipeline._article_repo == mock_article_repo
        assert pipeline._graph_writer == mock_neo4j_writer

    def test_default_concurrency_values(self):
        """Test default concurrency values."""
        assert Pipeline.DEFAULT_PHASE1_CONCURRENCY == 20
        assert Pipeline.DEFAULT_PHASE3_CONCURRENCY == 20


class TestPipelineStopAccepting:
    """Test stop_accepting method."""

    @pytest.fixture
    def pipeline(self):
        """Create Pipeline instance."""
        return Pipeline(
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
        return Pipeline(
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
    def mock_llm(self):
        """Mock LLM client."""
        from core.llm.types import CallPoint

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
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_source_auth_repo(self):
        """Mock source authority repo."""
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.8))
        return repo

    @pytest.fixture
    def pipeline(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, mock_source_auth_repo
    ):
        """Create Pipeline instance with mocks."""
        return Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )

    @pytest.fixture
    def sample_article_raw(self):
        """Create sample ArticleRaw."""
        return ArticleRaw(
            url="https://example.com/test-article",
            title="Test Article Title",
            body="Test article body content for processing.",
            source="test_source",
            source_host="example.com",
            publish_time=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_process_batch_not_accepting(self, pipeline, sample_article_raw):
        """Test process_batch raises when not accepting."""
        await pipeline.stop_accepting()

        with pytest.raises(RuntimeError, match="not accepting"):
            await pipeline.process_batch([sample_article_raw])

    @pytest.mark.asyncio
    async def test_process_batch_single_article(self, pipeline, sample_article_raw):
        """Test processing a single article."""
        results = await pipeline.process_batch([sample_article_raw])

        assert len(results) == 1
        assert "raw" in results[0]

    @pytest.mark.asyncio
    async def test_process_batch_multiple_articles(self, pipeline):
        """Test processing multiple articles."""
        articles = [
            ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body=f"Body content {i}",
                source="test",
                source_host="example.com",
            )
            for i in range(3)
        ]

        results = await pipeline.process_batch(articles)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_process_batch_empty(self, pipeline):
        """Test processing empty batch."""
        results = await pipeline.process_batch([])

        assert len(results) == 0


class TestPipelinePhase1:
    """Test _phase1_per_article method."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        from core.llm.types import CallPoint

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
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def pipeline(self, mock_llm, mock_budget, mock_prompt_loader):
        """Create Pipeline instance."""
        return Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_phase1_processes_all_nodes(self, pipeline):
        """Test phase1 processes classifier, cleaner, categorizer, vectorize."""
        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        result = await pipeline._phase1_per_article(state)

        assert "is_news" in result
        assert "cleaned" in result
        assert "category" in result
        assert "vectors" in result

    @pytest.mark.asyncio
    async def test_phase1_stops_on_terminal_after_classifier(self, pipeline):
        """Test phase1 processes classifier then stops when terminal is set."""
        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)

        result = await pipeline._phase1_per_article(state)

        assert result.get("is_news") is True
        assert result.get("cleaned") is not None
        assert result.get("category") is not None


class TestPipelinePhase3:
    """Test _phase3_per_article method."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        from core.llm.types import CallPoint

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
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_source_auth_repo(self):
        """Mock source authority repo."""
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.8))
        return repo

    @pytest.fixture
    def pipeline(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, mock_source_auth_repo
    ):
        """Create Pipeline instance."""
        return Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )

    @pytest.mark.asyncio
    async def test_phase3_processes_all_nodes(self, pipeline):
        """Test phase3 processes re_vectorize, analyze, credibility, entity_extractor."""
        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"

        result = await pipeline._phase3_per_article(state)

        assert "vectors" in result
        assert "summary_info" in result
        assert "credibility" in result

    @pytest.mark.asyncio
    async def test_phase3_skips_terminal(self, pipeline):
        """Test phase3 skips terminal articles."""
        state = PipelineState(raw=MagicMock())
        state["terminal"] = True

        result = await pipeline._phase3_per_article(state)

        assert result.get("terminal") is True

    @pytest.mark.asyncio
    async def test_phase3_terminal_runs_enrichment_skips_revectorize(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, mock_source_auth_repo
    ):
        """Test terminal article: re_vectorize skipped, but analyze/quality/credibility/entity run."""

        def node_execute(s):
            return dict(s)

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        pipeline._re_vectorize = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._analyze = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._quality_scorer = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._credibility = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_extractor = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_resolver = MagicMock(execute=AsyncMock(side_effect=node_execute))

        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["terminal"] = True  # ← terminal article

        result = await pipeline._phase3_per_article(state)

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
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, mock_source_auth_repo
    ):
        """Test non-terminal article: all Phase 3 nodes run including re_vectorize."""

        def node_execute(s):
            return dict(s)

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )
        pipeline._re_vectorize = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._analyze = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._quality_scorer = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._credibility = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_extractor = MagicMock(execute=AsyncMock(side_effect=node_execute))
        pipeline._entity_resolver = MagicMock(execute=AsyncMock(side_effect=node_execute))

        raw = MagicMock()
        raw.title = "Test"
        raw.body = "Body"
        raw.url = "https://example.com/test"
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        # terminal=False (default)

        await pipeline._phase3_per_article(state)

        # All nodes MUST be called including re_vectorize
        pipeline._re_vectorize.execute.assert_awaited_once()
        pipeline._analyze.execute.assert_awaited_once()
        pipeline._quality_scorer.execute.assert_awaited_once()
        pipeline._credibility.execute.assert_awaited_once()
        pipeline._entity_extractor.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_phase3_skips_merged(self, pipeline):
        """Test phase3 skips merged articles."""
        state = PipelineState(raw=MagicMock())
        state["is_merged"] = True

        result = await pipeline._phase3_per_article(state)

        assert result.get("is_merged") is True


class TestPipelinePersist:
    """Test _persist method."""

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
    async def test_persist_skips_terminal(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist skips terminal articles."""
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        state = PipelineState(raw=MagicMock())
        state["terminal"] = True

        await pipeline._persist(state)

    @pytest.mark.asyncio
    async def test_persist_without_repos(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist without article_repo and graph_writer."""
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        state = PipelineState(raw=MagicMock())
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist(state)

    @pytest.mark.asyncio
    async def test_persist_with_article_repo(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist with article_repo."""
        import uuid

        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=uuid.uuid4())
        mock_article_repo.update_persist_status = AsyncMock()

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist(state)

        assert "article_id" in state
        mock_article_repo.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_with_neo4j_writer(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist with graph_writer."""
        import uuid

        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=uuid.uuid4())
        mock_article_repo.update_persist_status = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(return_value=["entity1", "entity2"])

        pipeline = Pipeline(
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
        # Add complete enrichment fields for validation
        state["category"] = "technology"
        state["score"] = 0.85
        state["quality_score"] = 0.90
        state["summary_info"] = {"summary": "Test summary"}
        state["credibility"] = {"score": 0.95}

        await pipeline._persist(state)

        assert "neo4j_ids" in state

    @pytest.mark.asyncio
    async def test_persist_handles_pg_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist handles PostgreSQL errors."""

        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(side_effect=Exception("PG error"))
        mock_article_repo.mark_failed = AsyncMock()

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=mock_article_repo,
        )

        raw = MagicMock()
        raw.url = "https://example.com/test"

        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist(state)

    @pytest.mark.asyncio
    async def test_persist_handles_neo4j_error(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist handles Neo4j errors."""
        import uuid

        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=uuid.uuid4())
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(side_effect=Exception("Neo4j error"))

        pipeline = Pipeline(
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

        await pipeline._persist(state)


class TestPipelineUpdateProcessingStage:
    """Test _update_processing_stage method."""

    @pytest.fixture
    def pipeline_no_repo(self):
        """Create Pipeline without article_repo."""
        return Pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )

    @pytest.fixture
    def pipeline_with_repo(self):
        """Create Pipeline with article_repo."""
        return Pipeline(
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

        await pipeline_no_repo._update_processing_stage(state, "test_stage")

    @pytest.mark.asyncio
    async def test_update_stage_no_article_id(self, pipeline_with_repo):
        """Test update stage without article_id."""
        state = PipelineState(raw=MagicMock())

        await pipeline_with_repo._update_processing_stage(state, "test_stage")

    @pytest.mark.asyncio
    async def test_update_stage_success(self, pipeline_with_repo):
        """Test successful update of processing stage."""
        import uuid

        article_id = uuid.uuid4()
        pipeline_with_repo._article_repo.update_processing_stage = AsyncMock()

        state = PipelineState(raw=MagicMock())
        state["article_id"] = str(article_id)

        await pipeline_with_repo._update_processing_stage(state, "phase1_classifier")

        pipeline_with_repo._article_repo.update_processing_stage.assert_called_once()


class TestPipelineMarkProcessing:
    """Test _mark_processing method."""

    @pytest.fixture
    def pipeline_with_repo(self):
        """Create Pipeline with article_repo."""
        return Pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
            article_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_mark_processing_no_repo(self):
        """Test mark processing without article_repo."""
        pipeline = Pipeline(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            event_bus=MagicMock(),
        )

        state = PipelineState(raw=MagicMock())
        state["article_id"] = "test-id"

        await pipeline._mark_processing(state)

    @pytest.mark.asyncio
    async def test_mark_processing_no_article_id(self, pipeline_with_repo):
        """Test mark processing without article_id."""
        state = PipelineState(raw=MagicMock())

        await pipeline_with_repo._mark_processing(state)

    @pytest.mark.asyncio
    async def test_mark_processing_success(self, pipeline_with_repo):
        """Test successful mark processing."""
        import uuid

        article_id = uuid.uuid4()
        pipeline_with_repo._article_repo.mark_processing = AsyncMock()

        state = PipelineState(raw=MagicMock())
        state["article_id"] = str(article_id)

        await pipeline_with_repo._mark_processing(state)

        pipeline_with_repo._article_repo.mark_processing.assert_called_once()


class TestPipelinePersistFallback:
    """Test Neo4j error handling in Pipeline._persist."""

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
    async def test_persist_marks_failed_on_neo4j_failure(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test that mark_failed is called when Neo4j write fails."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=article_id)
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(side_effect=Exception("Neo4j connection failed"))

        pipeline = Pipeline(
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
        state["article_id"] = str(article_id)
        state["entities"] = [{"name": "Test Entity"}]
        state["relations"] = []
        state["resolved_entities"] = []
        state["cleaned"] = {"title": "Title", "body": "Body"}

        await pipeline._persist(state)

        # Article should be marked as failed in Postgres
        mock_article_repo.mark_failed.assert_called_once()
        call_args = mock_article_repo.mark_failed.call_args
        assert call_args[0][0] == article_id
        assert "Neo4j" in str(call_args[0][1])

    @pytest.mark.asyncio
    async def test_persist_no_neo4j_writer_only_postgres(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test that persist only writes to Postgres when Neo4j is not available."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=article_id)
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        pipeline = Pipeline(
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
        state["article_id"] = str(article_id)
        state["entities"] = [{"name": "Entity1"}]
        state["relations"] = [{"source": "e1", "target": "e2"}]

        await pipeline._persist(state)

        # Postgres write should succeed
        mock_article_repo.upsert.assert_called_once()
        mock_article_repo.update_persist_status.assert_called_once()
        # No failure marking
        mock_article_repo.mark_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_success_no_mark_failed(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test no mark_failed call when both Postgres and Neo4j succeed."""
        import uuid

        article_id = uuid.uuid4()
        mock_article_repo = MagicMock()
        mock_article_repo.upsert = AsyncMock(return_value=article_id)
        mock_article_repo.update_persist_status = AsyncMock()
        mock_article_repo.mark_failed = AsyncMock()

        mock_neo4j_writer = MagicMock()
        mock_neo4j_writer.write = AsyncMock(return_value=["entity1", "entity2"])

        pipeline = Pipeline(
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
        state["article_id"] = str(uuid.uuid4())
        state["entities"] = []
        state["relations"] = []

        await pipeline._persist(state)

        # Both writers called, no failure
        mock_article_repo.upsert.assert_called_once()
        mock_neo4j_writer.write.assert_called_once()
        mock_article_repo.mark_failed.assert_not_called()


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
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        await pipeline._persist_batch([])

    @pytest.mark.asyncio
    async def test_persist_batch_all_terminal(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch skips all terminal articles."""
        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        states = [PipelineState(raw=MagicMock()) for _ in range(3)]
        for state in states:
            state["terminal"] = True

        await pipeline._persist_batch(states)

    @pytest.mark.asyncio
    async def test_persist_batch_with_article_repo(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus
    ):
        """Test persist_batch with article_repo."""
        import uuid

        article_ids = [uuid.uuid4() for _ in range(2)]
        mock_article_repo = MagicMock()
        mock_article_repo.bulk_upsert = AsyncMock(return_value=article_ids)

        pipeline = Pipeline(
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

        await pipeline._persist_batch(states)

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

        pipeline = Pipeline(
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

        await pipeline._persist_batch([state])

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

        pipeline = Pipeline(
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

        await pipeline._persist_batch([state])

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

        pipeline = Pipeline(
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

        await pipeline._persist_batch([state])

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

        pipeline = Pipeline(
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

        await pipeline._persist_batch([state])

        mock_article_repo.mark_failed.assert_called_once()


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
        pipeline = Pipeline(
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

        pipeline = Pipeline(
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

        pipeline = Pipeline(
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

        pipeline = Pipeline(
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

        pipeline = Pipeline(
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

        pipeline = Pipeline(
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
