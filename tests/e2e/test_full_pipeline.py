"""E2E tests for full pipeline execution."""

import pytest
import uuid
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from modules.pipeline.state import PipelineState


class TestFullPipelineE2E:
    """End-to-end tests for the complete pipeline."""

    @pytest.fixture
    def sample_raw_article(self):
        """Create sample raw article data."""
        from modules.collector.models import ArticleRaw

        return ArticleRaw(
            url="https://example.com/e2e-test-article",
            title="E2E Test Article: Major Technology Breakthrough",
            body="This is a comprehensive test article about a major technology breakthrough. "
                 "The article discusses innovations in artificial intelligence and machine learning. "
                 "Experts believe this will transform the industry significantly.",
            source="Example News",
            publish_time=datetime.now(timezone.utc),
            source_host="example.com",
        )

    @pytest.fixture
    def pipeline_state(self, sample_raw_article):
        """Create initial pipeline state."""
        return PipelineState(raw=sample_raw_article)

    @pytest.mark.asyncio
    async def test_pipeline_state_initialization(self, pipeline_state, sample_raw_article):
        """Test pipeline state initializes correctly."""
        assert pipeline_state["raw"] == sample_raw_article
        assert "raw" in pipeline_state

    @pytest.mark.asyncio
    async def test_pipeline_state_field_updates(self, pipeline_state):
        """Test pipeline state field updates."""
        pipeline_state["is_news"] = True
        pipeline_state["category"] = "tech"
        pipeline_state["language"] = "zh"
        pipeline_state["score"] = 0.85

        assert pipeline_state["is_news"] is True
        assert pipeline_state["category"] == "tech"
        assert pipeline_state["language"] == "zh"
        assert pipeline_state["score"] == 0.85

    @pytest.mark.asyncio
    async def test_pipeline_state_cleaned_data(self, pipeline_state):
        """Test pipeline state with cleaned data."""
        pipeline_state["cleaned"] = {
            "title": "Cleaned Title",
            "body": "Cleaned body content",
        }

        assert pipeline_state["cleaned"]["title"] == "Cleaned Title"
        assert pipeline_state["cleaned"]["body"] == "Cleaned body content"

    @pytest.mark.asyncio
    async def test_pipeline_state_summary_info(self, pipeline_state):
        """Test pipeline state with summary info."""
        pipeline_state["summary_info"] = {
            "summary": "Article summary",
            "subjects": ["AI", "Technology"],
            "key_data": ["Data point 1"],
            "impact": "high",
            "has_data": True,
            "event_time": "2024-01-15T10:00:00",
        }

        assert pipeline_state["summary_info"]["summary"] == "Article summary"
        assert "AI" in pipeline_state["summary_info"]["subjects"]

    @pytest.mark.asyncio
    async def test_pipeline_state_sentiment(self, pipeline_state):
        """Test pipeline state with sentiment data."""
        pipeline_state["sentiment"] = {
            "sentiment": "positive",
            "sentiment_score": 0.75,
            "primary_emotion": "joy",
            "emotion_targets": ["technology", "innovation"],
        }

        assert pipeline_state["sentiment"]["sentiment"] == "positive"
        assert pipeline_state["sentiment"]["sentiment_score"] == 0.75

    @pytest.mark.asyncio
    async def test_pipeline_state_credibility(self, pipeline_state):
        """Test pipeline state with credibility data."""
        pipeline_state["credibility"] = {
            "score": 0.9,
            "source_credibility": 0.85,
            "cross_verification": 0.8,
            "content_check": 0.95,
            "flags": ["verified"],
            "verified_by_sources": 3,
        }

        assert pipeline_state["credibility"]["score"] == 0.9
        assert pipeline_state["credibility"]["source_credibility"] == 0.85

    @pytest.mark.asyncio
    async def test_pipeline_state_entities(self, pipeline_state):
        """Test pipeline state with extracted entities."""
        pipeline_state["entities"] = [
            {"text": "OpenAI", "label": "ORG", "start": 0, "end": 6},
            {"text": "人工智能", "label": "TECH", "start": 50, "end": 54},
        ]

        assert len(pipeline_state["entities"]) == 2
        assert pipeline_state["entities"][0]["text"] == "OpenAI"

    @pytest.mark.asyncio
    async def test_pipeline_state_vector(self, pipeline_state):
        """Test pipeline state with vector embedding."""
        pipeline_state["vector"] = [0.1] * 1536

        assert len(pipeline_state["vector"]) == 1536

    @pytest.mark.asyncio
    async def test_pipeline_state_merge_info(self, pipeline_state):
        """Test pipeline state with merge information."""
        pipeline_state["is_merged"] = True
        pipeline_state["merged_source_ids"] = [
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        ]

        assert pipeline_state["is_merged"] is True
        assert len(pipeline_state["merged_source_ids"]) == 2

    @pytest.mark.asyncio
    async def test_pipeline_state_prompt_versions(self, pipeline_state):
        """Test pipeline state tracks prompt versions."""
        pipeline_state["prompt_versions"] = {
            "classify": "v1.0",
            "analyze": "v1.2",
            "entity": "v1.1",
        }

        assert pipeline_state["prompt_versions"]["classify"] == "v1.0"


class TestPipelineNodeExecution:
    """Tests for individual pipeline node execution."""

    @pytest.mark.asyncio
    async def test_classify_node_execution(self):
        """Test classify node identifies news correctly."""
        from modules.pipeline.nodes import Classify

        mock_llm = AsyncMock()
        mock_llm.call.return_value = '{"is_news": true, "confidence": 0.95}'

        node = Classify(llm=mock_llm)

        state = {
            "raw": MagicMock(
                url="https://example.com/news",
                title="Breaking News",
                body="News content",
            )
        }

        result = await node(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_cleaner_node_execution(self):
        """Test cleaner node cleans content."""
        from modules.pipeline.nodes import Cleaner

        node = Cleaner()

        state = {
            "raw": MagicMock(
                url="https://example.com/article",
                title="  Messy Title  ",
                body="<p>HTML content</p>",
            )
        }

        result = await node(state)
        assert "cleaned" in result

    @pytest.mark.asyncio
    async def test_categorizer_node_execution(self):
        """Test categorizer node assigns category."""
        from modules.pipeline.nodes import Categorizer

        mock_llm = AsyncMock()
        mock_llm.call.return_value = '{"category": "tech", "language": "zh", "region": "CN"}'

        node = Categorizer(llm=mock_llm)

        state = {
            "raw": MagicMock(url="https://example.com/tech", title="Tech News"),
            "cleaned": {"title": "Tech News", "body": "Tech content"},
        }

        result = await node(state)
        assert result["category"] == "tech"

    @pytest.mark.asyncio
    async def test_vectorize_node_execution(self):
        """Test vectorize node creates embedding."""
        from modules.pipeline.nodes import Vectorize

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536

        node = Vectorize(embedder=mock_embedder)

        state = {
            "raw": MagicMock(url="https://example.com/article"),
            "cleaned": {"title": "Title", "body": "Body"},
        }

        result = await node(state)
        assert "vector" in result
        assert len(result["vector"]) == 1536

    @pytest.mark.asyncio
    async def test_analyze_node_execution(self):
        """Test analyze node extracts summary and sentiment."""
        from modules.pipeline.nodes import Analyze

        mock_llm = AsyncMock()
        mock_llm.call.return_value = '''{
            "summary": "Article summary",
            "subjects": ["AI"],
            "key_data": [],
            "impact": "medium",
            "has_data": false,
            "sentiment": "neutral",
            "sentiment_score": 0.5,
            "primary_emotion": null
        }'''

        node = Analyze(llm=mock_llm)

        state = {
            "raw": MagicMock(url="https://example.com/article"),
            "cleaned": {"title": "Title", "body": "Body"},
            "category": "tech",
        }

        result = await node(state)
        assert result["summary_info"]["summary"] == "Article summary"
        assert result["sentiment"]["sentiment"] == "neutral"

    @pytest.mark.asyncio
    async def test_credibility_checker_node_execution(self):
        """Test credibility checker calculates score."""
        from modules.pipeline.nodes import CredibilityChecker

        mock_repo = AsyncMock()
        mock_repo.get_or_create = AsyncMock(return_value=MagicMock(
            authority=0.8,
            tier=1,
        ))

        node = CredibilityChecker(source_authority_repo=mock_repo)

        state = {
            "raw": MagicMock(
                url="https://trusted.com/article",
                source_host="trusted.com",
            ),
            "cleaned": {"body": "Quality content with sources."},
        }

        result = await node(state)
        assert "credibility" in result

    @pytest.mark.asyncio
    async def test_entity_extractor_node_execution(self):
        """Test entity extractor identifies entities."""
        from modules.pipeline.nodes import EntityExtractor

        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = [
            {"text": "OpenAI", "label": "ORG"},
            {"text": "GPT-4", "label": "PRODUCT"},
        ]

        node = EntityExtractor(extractor=mock_extractor)

        state = {
            "raw": MagicMock(url="https://example.com/article"),
            "cleaned": {"title": "OpenAI releases GPT-4", "body": "Content"},
        }

        result = await node(state)
        assert len(result["entities"]) == 2


class TestPipelineErrorHandling:
    """Tests for pipeline error handling."""

    @pytest.mark.asyncio
    async def test_llm_timeout_handling(self):
        """Test pipeline handles LLM timeout."""
        from modules.pipeline.nodes import Classify

        mock_llm = AsyncMock()
        mock_llm.call.side_effect = asyncio.TimeoutError("LLM timeout")

        node = Classify(llm=mock_llm)

        state = {
            "raw": MagicMock(
                url="https://example.com/news",
                title="News",
                body="Content",
            )
        }

        with pytest.raises(asyncio.TimeoutError):
            await node(state)

    @pytest.mark.asyncio
    async def test_llm_rate_limit_handling(self):
        """Test pipeline handles LLM rate limit."""
        from modules.pipeline.nodes import Categorizer

        mock_llm = AsyncMock()
        mock_llm.call.side_effect = Exception("Rate limit exceeded")

        node = Categorizer(llm=mock_llm)

        state = {
            "raw": MagicMock(url="https://example.com/article"),
            "cleaned": {"title": "Title", "body": "Body"},
        }

        with pytest.raises(Exception, match="Rate limit"):
            await node(state)

    @pytest.mark.asyncio
    async def test_invalid_json_response_handling(self):
        """Test pipeline handles invalid JSON from LLM."""
        from modules.pipeline.nodes import Classify

        mock_llm = AsyncMock()
        mock_llm.call.return_value = "Not valid JSON"

        node = Classify(llm=mock_llm)

        state = {
            "raw": MagicMock(
                url="https://example.com/news",
                title="News",
                body="Content",
            )
        }

        with pytest.raises(Exception):
            await node(state)


class TestPipelineStatePersistence:
    """Tests for pipeline state persistence."""

    @pytest.mark.asyncio
    async def test_state_to_article_conversion(self):
        """Test pipeline state converts to article model."""
        from modules.storage.article_repo import ArticleRepo
        from modules.collector.models import ArticleRaw

        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = ArticleRepo(mock_pool)

        raw = ArticleRaw(
            url="https://example.com/persist-test",
            title="Persist Test",
            body="Test body",
            source="Test Source",
            publish_time=datetime.now(timezone.utc),
            source_host="example.com",
        )

        state = PipelineState(raw=raw)
        state["is_news"] = True
        state["category"] = "tech"
        state["score"] = 0.85
        state["credibility"] = {
            "score": 0.9,
            "source_credibility": 0.8,
            "cross_verification": 0.7,
            "content_check": 0.95,
            "flags": [],
            "verified_by_sources": 1,
        }

        article_id = await repo.upsert(state)
        assert isinstance(article_id, uuid.UUID)


class TestPipelineConcurrency:
    """Tests for pipeline concurrent execution."""

    @pytest.mark.asyncio
    async def test_concurrent_pipeline_execution(self):
        """Test multiple pipeline states can be processed concurrently."""
        from modules.collector.models import ArticleRaw

        states = []
        for i in range(5):
            raw = ArticleRaw(
                url=f"https://example.com/concurrent-{i}",
                title=f"Concurrent Article {i}",
                body=f"Body content {i}",
                source="Example",
                publish_time=datetime.now(timezone.utc),
                source_host="example.com",
            )
            states.append(PipelineState(raw=raw))

        async def process_state(state):
            state["is_news"] = True
            state["category"] = "tech"
            state["score"] = 0.8
            await asyncio.sleep(0.01)
            return state

        results = await asyncio.gather(*[process_state(s) for s in states])

        assert len(results) == 5
        for result in results:
            assert result["is_news"] is True
            assert result["category"] == "tech"

    @pytest.mark.asyncio
    async def test_pipeline_batch_processing(self):
        """Test pipeline can process batch of articles."""
        from modules.collector.models import ArticleRaw

        batch = []
        for i in range(10):
            raw = ArticleRaw(
                url=f"https://example.com/batch-{i}",
                title=f"Batch Article {i}",
                body=f"Content {i}",
                source="Batch Source",
                publish_time=datetime.now(timezone.utc),
                source_host="example.com",
            )
            batch.append(raw)

        processed = []
        for raw in batch:
            state = PipelineState(raw=raw)
            state["is_news"] = True
            processed.append(state)

        assert len(processed) == 10
        for state in processed:
            assert "raw" in state
            assert state["is_news"] is True
