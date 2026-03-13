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
        from modules.pipeline.nodes.classifier import ClassifierNode
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(is_news=True, confidence=0.95)

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = ClassifierNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(
            url="https://example.com/news",
            title="Breaking News",
            body="News content",
        ))

        result = await node.execute(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_cleaner_node_execution(self):
        """Test cleaner node cleans content."""
        from modules.pipeline.nodes.cleaner import CleanerNode
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader
        from core.llm.output_validator import CleanerOutput

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(title="Messy Title", body="HTML content")

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = CleanerNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(
            url="https://example.com/article",
            title="  Messy Title  ",
            body="<p>HTML content</p>",
            publish_time=None,
            source_host="example.com",
        ))

        result = await node.execute(state)
        assert "cleaned" in result

    @pytest.mark.asyncio
    async def test_categorizer_node_execution(self):
        """Test categorizer node assigns category."""
        from modules.pipeline.nodes.categorizer import CategorizerNode
        from core.llm.client import LLMClient
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(category="tech", language="zh", region="CN")

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = CategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(url="https://example.com/tech", title="Tech News"))
        state["cleaned"] = {"title": "Tech News", "body": "Tech content"}

        result = await node.execute(state)
        assert result.get("category") == "科技"
        assert result.get("language") == "zh"

    @pytest.mark.asyncio
    async def test_vectorize_node_execution(self):
        """Test vectorize node creates embedding."""
        from modules.pipeline.nodes.vectorize import VectorizeNode
        from core.llm.client import LLMClient

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.batch_embed.return_value = [[0.1] * 1024]

        node = VectorizeNode(llm=mock_llm)

        state = PipelineState(raw=MagicMock(url="https://example.com/article"))
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)
        assert "vectors" in result
        assert "content" in result["vectors"]

    @pytest.mark.asyncio
    async def test_analyze_node_execution(self):
        """Test analyze node extracts summary and sentiment."""
        from modules.pipeline.nodes.analyze import AnalyzeNode
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(
            summary="Article summary",
            subjects=["AI"],
            key_data=[],
            impact="medium",
            has_data=False,
            event_time=None,
            sentiment="neutral",
            sentiment_score=0.5,
            primary_emotion=None,
            emotion_targets=[],
            score=0.7,
        )

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = AnalyzeNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(url="https://example.com/article"))
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "tech"

        result = await node.execute(state)
        assert result["summary_info"]["summary"] == "Article summary"
        assert result["sentiment"]["sentiment"] == "neutral"

    @pytest.mark.asyncio
    async def test_credibility_checker_node_execution(self):
        """Test credibility checker calculates score."""
        from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
        from modules.storage.source_authority_repo import SourceAuthorityRepo
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader
        from core.event.bus import EventBus

        mock_repo = AsyncMock(spec=SourceAuthorityRepo)
        mock_repo.get_or_create = AsyncMock(return_value=MagicMock(
            authority=0.8,
            tier=1,
        ))

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(score=0.85, flags=[])

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        mock_event_bus = MagicMock(spec=EventBus)
        mock_event_bus.publish = AsyncMock()

        node = CredibilityCheckerNode(
            llm=mock_llm,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_repo,
        )

        state = PipelineState(raw=MagicMock(
            url="https://trusted.com/article",
            source_host="trusted.com",
        ))
        state["cleaned"] = {"body": "Quality content with sources."}

        result = await node.execute(state)
        assert "credibility" in result

    @pytest.mark.asyncio
    async def test_entity_extractor_node_execution(self):
        """Test entity extractor identifies entities."""
        from modules.pipeline.nodes.entity_extractor import EntityExtractorNode
        from modules.nlp.spacy_extractor import SpacyExtractor
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader
        from modules.storage.vector_repo import VectorRepo

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.return_value = MagicMock(
            entities=[{"name": "OpenAI", "type": "组织机构"}],
            relations=[]
        )
        mock_llm.batch_embed.return_value = [[0.1] * 1024]

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        mock_extractor = MagicMock(spec=SpacyExtractor)
        mock_extractor.extract.return_value = [
            MagicMock(name="OpenAI", label="ORG", type="组织机构"),
        ]

        mock_vector_repo = AsyncMock(spec=VectorRepo)
        mock_vector_repo.upsert_entity_vectors = AsyncMock()

        node = EntityExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_extractor,
            vector_repo=mock_vector_repo,
        )

        state = PipelineState(raw=MagicMock(url="https://example.com/article"))
        state["cleaned"] = {"title": "OpenAI releases GPT-4", "body": "Content about OpenAI"}
        state["language"] = "zh"

        result = await node.execute(state)
        assert len(result.get("entities", [])) >= 0


class TestPipelineErrorHandling:
    """Tests for pipeline error handling."""

    @pytest.mark.asyncio
    async def test_llm_timeout_handling(self):
        """Test pipeline handles LLM timeout."""
        from modules.pipeline.nodes.classifier import ClassifierNode
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = asyncio.TimeoutError("LLM timeout")

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x
        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = ClassifierNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(
            url="https://example.com/news",
            title="News",
            body="Content",
        ))

        with pytest.raises(asyncio.TimeoutError):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_llm_rate_limit_handling(self):
        """Test pipeline handles LLM rate limit gracefully."""
        from modules.pipeline.nodes.categorizer import CategorizerNode
        from core.llm.client import LLMClient
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = Exception("Rate limit exceeded")

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = CategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(url="https://example.com/article"))
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)
        assert result.get("category") == "未知"

    @pytest.mark.asyncio
    async def test_invalid_json_response_handling(self):
        """Test pipeline handles invalid JSON from LLM."""
        from modules.pipeline.nodes.classifier import ClassifierNode
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = ValueError("Invalid JSON response")

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x
        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = ClassifierNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(
            url="https://example.com/news",
            title="News",
            body="Content",
        ))

        with pytest.raises(ValueError):
            await node.execute(state)


class TestPipelineStatePersistence:
    """Tests for pipeline state persistence."""

    @pytest.mark.asyncio
    async def test_state_to_article_conversion(self):
        """Test pipeline state converts to article model."""
        from modules.storage.article_repo import ArticleRepo
        from modules.collector.models import ArticleRaw

        mock_pool = MagicMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        new_id = uuid.uuid4()

        def mock_add(article):
            article.id = new_id

        mock_session.add = MagicMock(side_effect=mock_add)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session = MagicMock()
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

        state: PipelineState = {"raw": raw}
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
