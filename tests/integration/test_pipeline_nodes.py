# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for pipeline nodes.

Tests the integration between pipeline nodes and their dependencies.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CleanerContent
from modules.collector.models import ArticleRaw
from modules.pipeline.state import PipelineState


@pytest.fixture
def sample_raw_article():
    """Create sample raw article for testing."""
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article: Major Technology Breakthrough",
        body="This is a comprehensive test article about a major technology breakthrough. "
        "The article discusses innovations in artificial intelligence and machine learning. "
        "Experts believe this will transform the industry significantly.",
        source="Example News",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def pipeline_state(sample_raw_article):
    """Create initial pipeline state."""
    return PipelineState(raw=sample_raw_article)


@pytest.fixture
def mock_llm_client():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager."""
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Test prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_vector_repo():
    """Mock vector repository."""
    mock = AsyncMock()
    mock.batch_find_similar = AsyncMock(return_value={})
    return mock


@pytest.fixture
def mock_spacy_extractor():
    """Mock spaCy extractor."""
    extractor = MagicMock()
    extractor.extract = MagicMock(return_value=[])
    return extractor


class TestClassifierNodeIntegration:
    """Integration tests for ClassifierNode."""

    @pytest.mark.asyncio
    async def test_classify_news_article(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test classification of a news article."""
        from core.llm.output_validator import ClassifierOutput
        from modules.pipeline.nodes.classifier import ClassifierNode

        mock_llm_client.call = AsyncMock(
            return_value=ClassifierOutput(is_news=True, confidence=0.95)
        )

        node = ClassifierNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert result["is_news"] is True
        assert result.get("terminal") is False
        assert "classifier" in result.get("prompt_versions", {})

    @pytest.mark.asyncio
    async def test_classify_non_news_content(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test classification of non-news content."""
        from core.llm.output_validator import ClassifierOutput
        from modules.pipeline.nodes.classifier import ClassifierNode

        mock_llm_client.call = AsyncMock(
            return_value=ClassifierOutput(is_news=False, confidence=0.90)
        )

        node = ClassifierNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert result["is_news"] is False
        assert result.get("terminal") is True

    @pytest.mark.asyncio
    async def test_classify_with_truncation(
        self,
        mock_llm_client,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test classification with long content that needs truncation."""
        from core.llm.output_validator import ClassifierOutput
        from core.llm.token_budget import TokenBudgetManager
        from modules.pipeline.nodes.classifier import ClassifierNode

        real_budget = TokenBudgetManager()

        mock_llm_client.call = AsyncMock(
            return_value=ClassifierOutput(is_news=True, confidence=0.85)
        )

        node = ClassifierNode(
            llm=mock_llm_client,
            budget=real_budget,
            prompt_loader=mock_prompt_loader,
        )

        long_body = "Test content. " * 1000
        pipeline_state["raw"].body = long_body

        result = await node.execute(pipeline_state)

        assert result["is_news"] is True
        mock_llm_client.call.assert_called_once()


class TestCleanerNodeIntegration:
    """Integration tests for CleanerNode."""

    @pytest.mark.asyncio
    async def test_clean_article_content(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test cleaning article content."""
        from core.llm.output_validator import CleanerOutput
        from modules.pipeline.nodes.cleaner import CleanerNode

        mock_llm_client.call = AsyncMock(
            return_value=CleanerOutput(
                content=CleanerContent(
                    title="Cleaned Title",
                    body="Cleaned body content without markup tags.",
                )
            )
        )

        node = CleanerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert "cleaned" in result
        assert result["cleaned"]["title"] == "Cleaned Title"
        assert result["cleaned"]["body"] == "Cleaned body content without markup tags."

    @pytest.mark.asyncio
    async def test_cleaner_skips_terminal_state(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test cleaner skips processing for terminal states."""
        from modules.pipeline.nodes.cleaner import CleanerNode

        pipeline_state["terminal"] = True

        node = CleanerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        mock_llm_client.call.assert_not_called()
        assert "cleaned" not in result

    @pytest.mark.asyncio
    async def test_cleaner_fallback_on_failure(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test cleaner falls back to original content on failure."""
        from modules.pipeline.nodes.cleaner import CleanerNode

        mock_llm_client.call = AsyncMock(side_effect=Exception("LLM error"))

        node = CleanerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert "cleaned" in result
        assert result["cleaned"]["title"] == pipeline_state["raw"].title


class TestCategorizerNodeIntegration:
    """Integration tests for CategorizerNode."""

    @pytest.mark.asyncio
    async def test_categorize_article(
        self,
        mock_llm_client,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test article categorization."""
        from core.llm.output_validator import CategorizerOutput
        from modules.pipeline.nodes.categorizer import CategorizerNode

        mock_llm_client.call = AsyncMock(
            return_value=CategorizerOutput(
                category="technology",
                language="zh",
                region="CN",
            )
        )

        pipeline_state["cleaned"] = {
            "title": "Tech News",
            "body": "Technology content",
        }

        node = CategorizerNode(
            llm=mock_llm_client,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert result["category"] == "科技"
        assert result["language"] == "zh"
        assert result["region"] == "CN"

    @pytest.mark.asyncio
    async def test_categorizer_normalizes_category(
        self,
        mock_llm_client,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test category normalization to Chinese."""
        from core.llm.output_validator import CategorizerOutput
        from modules.pipeline.nodes.categorizer import CategorizerNode

        test_cases = [
            ("politics", "政治"),
            ("military", "军事"),
            ("economy", "经济"),
            ("technology", "科技"),
            ("society", "社会"),
            ("culture", "文化"),
            ("sports", "体育"),
            ("international", "国际"),
        ]

        for english, chinese in test_cases:
            mock_llm_client.call = AsyncMock(
                return_value=CategorizerOutput(
                    category=english,
                    language="en",
                    region="US",
                )
            )

            pipeline_state["cleaned"] = {"title": "Test", "body": "Content"}
            pipeline_state.pop("category", None)

            node = CategorizerNode(
                llm=mock_llm_client,
                prompt_loader=mock_prompt_loader,
            )

            result = await node.execute(pipeline_state)
            assert result["category"] == chinese, f"Expected {chinese} for {english}"

    @pytest.mark.asyncio
    async def test_categorizer_fallback_on_failure(
        self,
        mock_llm_client,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test categorizer uses defaults on failure."""
        from modules.pipeline.nodes.categorizer import CategorizerNode

        mock_llm_client.call = AsyncMock(side_effect=Exception("LLM error"))

        pipeline_state["cleaned"] = {
            "title": "Test",
            "body": "Content",
        }

        node = CategorizerNode(
            llm=mock_llm_client,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert result["category"] == "社会"
        assert result["language"] == "en"


class TestVectorizeNodeIntegration:
    """Integration tests for VectorizeNode."""

    @pytest.mark.asyncio
    async def test_vectorize_content(
        self,
        mock_llm_client,
        pipeline_state,
    ):
        """Test content vectorization."""
        from modules.pipeline.nodes.vectorize import VectorizeNode

        mock_embedding = [0.1] * 1024
        mock_llm_client.batch_embed = AsyncMock(return_value=[mock_embedding])

        pipeline_state["cleaned"] = {
            "title": "Test Title",
            "body": "Test body content",
        }

        node = VectorizeNode(llm=mock_llm_client)

        result = await node.execute(pipeline_state)

        assert "vectors" in result
        assert "content" in result["vectors"]
        assert len(result["vectors"]["content"]) == 1024

    @pytest.mark.asyncio
    async def test_vectorize_skips_terminal_state(
        self,
        mock_llm_client,
        pipeline_state,
    ):
        """Test vectorization skips terminal states."""
        from modules.pipeline.nodes.vectorize import VectorizeNode

        pipeline_state["terminal"] = True

        node = VectorizeNode(llm=mock_llm_client)

        result = await node.execute(pipeline_state)

        mock_llm_client.batch_embed.assert_not_called()


class TestBatchMergerNodeIntegration:
    """Integration tests for BatchMergerNode."""

    @pytest.mark.asyncio
    async def test_batch_merge_similar_articles(
        self,
        mock_llm_client,
        mock_prompt_loader,
        mock_vector_repo,
    ):
        """Test merging similar articles in a batch."""
        from core.llm.output_validator import MergerOutput
        from modules.pipeline.nodes.batch_merger import BatchMergerNode

        mock_llm_client.call = AsyncMock(
            return_value=MergerOutput(
                merged_title="Merged Title",
                merged_body="Merged body content from multiple sources.",
            )
        )

        states = []
        for i in range(3):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Similar Article {i}",
                body="Similar content about the same topic.",
                source=f"Source {i}",
                publish_time=datetime.now(UTC),
                source_host="example.com",
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {
                "title": raw.title,
                "body": raw.body,
            }
            state["category"] = "科技"
            state["vectors"] = {"content": [0.1 + i * 0.01] * 1024}
            states.append(state)

        node = BatchMergerNode(
            llm=mock_llm_client,
            prompt_loader=mock_prompt_loader,
            vector_repo=mock_vector_repo,
        )

        result_states = await node.execute_batch(states)

        assert len(result_states) == 3

    @pytest.mark.asyncio
    async def test_batch_merge_respects_category(
        self,
        mock_llm_client,
        mock_prompt_loader,
        mock_vector_repo,
    ):
        """Test that articles with different categories are not merged."""
        from modules.pipeline.nodes.batch_merger import BatchMergerNode

        states = []
        categories = ["科技", "政治", "经济"]

        for i, cat in enumerate(categories):
            raw = ArticleRaw(
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
                body="Content",
                source="Source",
                publish_time=datetime.now(UTC),
                source_host="example.com",
            )
            state = PipelineState(raw=raw)
            state["cleaned"] = {"title": raw.title, "body": raw.body}
            state["category"] = cat
            state["vectors"] = {"content": [0.5] * 1024}
            states.append(state)

        node = BatchMergerNode(
            llm=mock_llm_client,
            prompt_loader=mock_prompt_loader,
            vector_repo=mock_vector_repo,
        )

        result_states = await node.execute_batch(states)

        for state in result_states:
            assert state.get("is_merged") is not True


class TestAnalyzeNodeIntegration:
    """Integration tests for AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_analyze_article(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test article analysis for summary and sentiment."""
        from core.llm.output_validator import AnalyzeOutput
        from modules.pipeline.nodes.analyze import AnalyzeNode

        mock_llm_client.call = AsyncMock(
            return_value=AnalyzeOutput(
                summary="This is a summary of the article.",
                event_time="2024-01-15T10:00:00",
                subjects=["AI", "Technology"],
                key_data=["Key data point"],
                impact="High impact on the industry",
                has_data=True,
                sentiment="positive",
                sentiment_score=0.75,
                primary_emotion="optimistic",
                emotion_targets=["technology", "innovation"],
                score=0.85,
            )
        )

        pipeline_state["cleaned"] = {
            "title": "Test Title",
            "body": "Test body content",
        }
        pipeline_state["category"] = "科技"

        node = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        assert "summary_info" in result
        assert result["summary_info"]["summary"] == "This is a summary of the article."
        assert "sentiment" in result
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_analyze_skips_merged_articles(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test analysis skips merged articles."""
        from modules.pipeline.nodes.analyze import AnalyzeNode

        pipeline_state["is_merged"] = True
        pipeline_state["cleaned"] = {"title": "Test", "body": "Content"}

        node = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        result = await node.execute(pipeline_state)

        mock_llm_client.call.assert_not_called()


class TestCredibilityCheckerNodeIntegration:
    """Integration tests for CredibilityCheckerNode."""

    @pytest.mark.asyncio
    async def test_check_credibility(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        mock_vector_repo,
        pipeline_state,
    ):
        """Test credibility checking."""
        from core.event.bus import EventBus
        from core.llm.output_validator import CredibilityOutput
        from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode

        mock_llm_client.call = AsyncMock(return_value=CredibilityOutput(score=0.85, flags=[]))

        mock_source_auth_repo = AsyncMock()
        mock_source_auth_repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.80))

        mock_event_bus = MagicMock(spec=EventBus)
        mock_event_bus.publish = AsyncMock()

        pipeline_state["cleaned"] = {
            "title": "Test Title",
            "body": "Quality content with verified sources.",
            "source_host": "trusted.com",
        }
        pipeline_state["summary_info"] = {"summary": "Summary"}

        node = CredibilityCheckerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )

        result = await node.execute(pipeline_state)

        assert "credibility" in result
        assert 0 <= result["credibility"]["score"] <= 1
        assert "source_credibility" in result["credibility"]

    @pytest.mark.asyncio
    async def test_credibility_with_cross_verification(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test credibility with cross-verification sources."""
        from core.event.bus import EventBus
        from core.llm.output_validator import CredibilityOutput
        from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode

        mock_llm_client.call = AsyncMock(return_value=CredibilityOutput(score=0.90, flags=[]))

        mock_source_auth_repo = AsyncMock()
        mock_source_auth_repo.get_or_create = AsyncMock(return_value=MagicMock(authority=0.85))

        mock_event_bus = MagicMock(spec=EventBus)
        mock_event_bus.publish = AsyncMock()

        pipeline_state["cleaned"] = {
            "title": "Test",
            "body": "Content",
            "source_host": "example.com",
        }
        pipeline_state["summary_info"] = {"summary": "Summary"}
        pipeline_state["merged_source_ids"] = [
            "https://source1.com",
            "https://source2.com",
            "https://source3.com",
        ]

        node = CredibilityCheckerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            event_bus=mock_event_bus,
            source_auth_repo=mock_source_auth_repo,
        )

        result = await node.execute(pipeline_state)

        # Cross-verification was removed; verify the credibility dict
        assert "score" in result["credibility"]
        assert "source_credibility" in result["credibility"]
        assert "content_check" in result["credibility"]
        assert "timeliness" in result["credibility"]
        assert "flags" in result["credibility"]


class TestEntityExtractorNodeIntegration:
    """Integration tests for EntityExtractorNode."""

    @pytest.mark.asyncio
    async def test_extract_entities(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        mock_spacy_extractor,
        mock_vector_repo,
        pipeline_state,
    ):
        """Test entity extraction."""
        from core.llm.output_validator import EntityExtractorOutput
        from modules.nlp.spacy_extractor import SpacyEntity
        from modules.pipeline.nodes.entity_extractor import EntityExtractorNode

        mock_spacy_entity = MagicMock(spec=SpacyEntity)
        mock_spacy_entity.name = "OpenAI"
        mock_spacy_entity.type = "组织机构"
        mock_spacy_entity.label = "ORG"
        mock_spacy_extractor.extract = MagicMock(return_value=[mock_spacy_entity])

        mock_llm_client.call = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "OpenAI", "type": "组织机构"}],
                relations=[],
            )
        )
        mock_llm_client.batch_embed = AsyncMock(return_value=[[0.1] * 1024])

        pipeline_state["cleaned"] = {
            "title": "OpenAI releases GPT-4",
            "body": "OpenAI announced their new model.",
        }
        pipeline_state["language"] = "zh"

        node = EntityExtractorNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy_extractor,
            vector_repo=mock_vector_repo,
        )

        result = await node.execute(pipeline_state)

        assert "entities" in result
        assert "relations" in result
        assert len(result["entities"]) >= 0

    @pytest.mark.asyncio
    async def test_entity_extractor_handles_spacy_failure(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        mock_vector_repo,
        pipeline_state,
    ):
        """Test entity extractor handles spaCy failure gracefully."""
        from core.llm.output_validator import EntityExtractorOutput
        from modules.pipeline.nodes.entity_extractor import EntityExtractorNode

        mock_spacy = MagicMock()
        mock_spacy.extract = MagicMock(side_effect=Exception("spaCy error"))

        mock_llm_client.call = AsyncMock(
            return_value=EntityExtractorOutput(entities=[], relations=[])
        )
        mock_llm_client.batch_embed = AsyncMock(return_value=[])

        pipeline_state["cleaned"] = {"title": "Test", "body": "Content"}
        pipeline_state["language"] = "zh"

        node = EntityExtractorNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy,
            vector_repo=mock_vector_repo,
        )

        result = await node.execute(pipeline_state)

        assert result["entities"] == []
        assert result["relations"] == []


class TestPipelineNodeChain:
    """Integration tests for pipeline node chain execution."""

    @pytest.mark.asyncio
    async def test_full_pipeline_chain(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        mock_spacy_extractor,
        mock_vector_repo,
        sample_raw_article,
    ):
        """Test executing full pipeline node chain."""
        from core.llm.output_validator import (
            AnalyzeOutput,
            CategorizerOutput,
            ClassifierOutput,
            CleanerOutput,
        )
        from modules.pipeline.nodes.analyze import AnalyzeNode
        from modules.pipeline.nodes.categorizer import CategorizerNode
        from modules.pipeline.nodes.classifier import ClassifierNode
        from modules.pipeline.nodes.cleaner import CleanerNode
        from modules.pipeline.nodes.vectorize import VectorizeNode

        state = PipelineState(raw=sample_raw_article)

        mock_llm_client.call = AsyncMock()
        mock_llm_client.call.side_effect = [
            ClassifierOutput(is_news=True, confidence=0.95),
            CleanerOutput(content=CleanerContent(title="Cleaned Title", body="Cleaned body")),
            CategorizerOutput(category="technology", language="zh", region="CN"),
            AnalyzeOutput(
                summary="Summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                sentiment="neutral",
                sentiment_score=0.5,
                primary_emotion="客观",
                emotion_targets=[],
                score=0.7,
            ),
        ]
        mock_llm_client.batch_embed = AsyncMock(return_value=[[0.1] * 1024])

        classifier = ClassifierNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        cleaner = CleanerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        categorizer = CategorizerNode(
            llm=mock_llm_client,
            prompt_loader=mock_prompt_loader,
        )
        vectorize = VectorizeNode(llm=mock_llm_client)
        analyze = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        state = await classifier.execute(state)
        assert state["is_news"] is True

        state = await cleaner.execute(state)
        assert "cleaned" in state

        state = await categorizer.execute(state)
        assert state["category"] == "科技"

        state = await vectorize.execute(state)
        assert "vectors" in state

        state = await analyze.execute(state)
        assert "summary_info" in state
        assert "sentiment" in state

    @pytest.mark.asyncio
    async def test_pipeline_stops_for_non_news(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        sample_raw_article,
    ):
        """Test pipeline stops processing for non-news content."""
        from core.llm.output_validator import ClassifierOutput
        from modules.pipeline.nodes.classifier import ClassifierNode
        from modules.pipeline.nodes.cleaner import CleanerNode

        state = PipelineState(raw=sample_raw_article)

        mock_llm_client.call = AsyncMock(
            return_value=ClassifierOutput(is_news=False, confidence=0.90)
        )

        classifier = ClassifierNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        cleaner = CleanerNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )

        state = await classifier.execute(state)
        assert state["is_news"] is False
        assert state["terminal"] is True

        state = await cleaner.execute(state)
        assert "cleaned" not in state


# =============================================================================
# Migrated from E2E tests (tests/e2e/test_full_pipeline.py)
# =============================================================================


class TestPipelineStateIntegration:
    """Integration tests for PipelineState behavior (migrated from E2E)."""

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


class TestPipelineConcurrencyIntegration:
    """Integration tests for pipeline concurrency (migrated from E2E)."""

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
                publish_time=datetime.now(UTC),
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
                publish_time=datetime.now(UTC),
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


class TestPipelineErrorHandlingIntegration:
    """Integration tests for pipeline error handling (migrated from E2E)."""

    @pytest.mark.asyncio
    async def test_llm_timeout_handling(self):
        """Test pipeline handles LLM timeout."""
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader
        from modules.pipeline.nodes.classifier import ClassifierNode

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = TimeoutError("LLM timeout")

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x
        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = ClassifierNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(
            raw=MagicMock(
                url="https://example.com/news",
                title="News",
                body="Content",
            )
        )

        with pytest.raises(asyncio.TimeoutError):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_llm_rate_limit_handling(self):
        """Test pipeline handles LLM rate limit gracefully."""
        from core.llm.client import LLMClient
        from core.prompt.loader import PromptLoader
        from modules.pipeline.nodes.categorizer import CategorizerNode

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = Exception("Rate limit exceeded")

        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = CategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)

        state = PipelineState(raw=MagicMock(url="https://example.com/article"))
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)
        assert result.get("category") == "社会"

    @pytest.mark.asyncio
    async def test_invalid_json_response_handling(self):
        """Test pipeline handles invalid JSON from LLM."""
        from core.llm.client import LLMClient
        from core.llm.token_budget import TokenBudgetManager
        from core.prompt.loader import PromptLoader
        from modules.pipeline.nodes.classifier import ClassifierNode

        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.call.side_effect = ValueError("Invalid JSON response")

        mock_budget = MagicMock(spec=TokenBudgetManager)
        mock_budget.truncate = lambda x, y: x
        mock_prompt_loader = MagicMock(spec=PromptLoader)
        mock_prompt_loader.get_version.return_value = "v1.0"

        node = ClassifierNode(llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader)

        state = PipelineState(
            raw=MagicMock(
                url="https://example.com/news",
                title="News",
                body="Content",
            )
        )

        with pytest.raises(ValueError):
            await node.execute(state)


class TestCleanerNodeExtra:
    """Extra integration tests for CleanerNode migrated from unit tests."""

    @pytest.mark.asyncio
    async def test_cleaner_node_truncation(
        self,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test cleaner uses token truncation."""
        from core.llm.output_validator import CleanerContent, CleanerOutput
        from modules.pipeline.nodes.cleaner import CleanerNode

        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(
            return_value=CleanerOutput(
                content=CleanerContent(title="Title", body="Body"),
                tags=[],
                entities=[],
            )
        )

        mock_budget = MagicMock()
        mock_budget.truncate = MagicMock(return_value="truncated text")

        node = CleanerNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        await node.execute(pipeline_state)
        mock_budget.truncate.assert_called()


class TestAnalyzeNodeExtra:
    """Extra integration tests for AnalyzeNode migrated from unit tests."""

    @pytest.mark.asyncio
    async def test_analyze_node_summary(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test analyze generates summary."""
        from core.llm.output_validator import AnalyzeOutput
        from modules.pipeline.nodes.analyze import AnalyzeNode

        mock_llm_client.call = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="Impact",
                has_data=False,
                sentiment="neutral",
                sentiment_score=0.5,
                primary_emotion="平静",
                emotion_targets=[],
                score=0.5,
            )
        )
        pipeline_state["cleaned"] = {"title": "Title", "body": "Body"}
        pipeline_state["category"] = "科技"

        node = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        result = await node.execute(pipeline_state)
        assert "summary_info" in result

    @pytest.mark.asyncio
    async def test_analyze_node_sentiment(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test analyze extracts sentiment."""
        from core.llm.output_validator import AnalyzeOutput
        from modules.pipeline.nodes.analyze import AnalyzeNode

        mock_llm_client.call = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="Impact",
                has_data=False,
                sentiment="positive",
                sentiment_score=0.9,
                primary_emotion="振奋",
                emotion_targets=["target"],
                score=0.8,
            )
        )
        pipeline_state["cleaned"] = {"title": "Title", "body": "Body"}
        pipeline_state["category"] = "科技"

        node = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        result = await node.execute(pipeline_state)
        assert "sentiment" in result

    @pytest.mark.asyncio
    async def test_analyze_node_score(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        pipeline_state,
    ):
        """Test analyze calculates score."""
        from core.llm.output_validator import AnalyzeOutput
        from modules.pipeline.nodes.analyze import AnalyzeNode

        mock_llm_client.call = AsyncMock(
            return_value=AnalyzeOutput(
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
                score=0.85,
            )
        )
        pipeline_state["cleaned"] = {"title": "Title", "body": "Body"}
        pipeline_state["category"] = "科技"

        node = AnalyzeNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
        )
        result = await node.execute(pipeline_state)
        assert result.get("score") == 0.85


class TestEntityExtractorNodeExtra:
    """Extra integration tests for EntityExtractorNode migrated from unit tests."""

    @pytest.mark.asyncio
    async def test_entity_extractor_spacy(
        self,
        mock_llm_client,
        mock_budget,
        mock_prompt_loader,
        mock_spacy_extractor,
        mock_vector_repo,
        pipeline_state,
    ):
        """Test entity extractor uses spaCy."""
        from core.llm.output_validator import EntityExtractorOutput
        from modules.nlp.spacy_extractor import SpacyEntity
        from modules.pipeline.nodes.entity_extractor import EntityExtractorNode

        mock_spacy_entity = MagicMock(spec=SpacyEntity)
        mock_spacy_entity.name = "张三"
        mock_spacy_entity.type = "人物"
        mock_spacy_entity.label = "PER"
        mock_spacy_extractor.extract = MagicMock(return_value=[mock_spacy_entity])

        mock_llm_client.call = AsyncMock(
            return_value=EntityExtractorOutput(
                entities=[{"name": "张三", "type": "人物"}],
                relations=[],
            )
        )
        mock_llm_client.batch_embed = AsyncMock(return_value=[[0.1] * 1024])

        pipeline_state["cleaned"] = {"title": "Title", "body": "Body"}
        pipeline_state["language"] = "zh"

        node = EntityExtractorNode(
            llm=mock_llm_client,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            spacy=mock_spacy_extractor,
            vector_repo=mock_vector_repo,
        )
        result = await node.execute(pipeline_state)
        mock_spacy_extractor.extract.assert_called()


class TestUnionFindAlgorithm:
    """Integration tests for UnionFind algorithm from BatchMergerNode."""

    def test_similarity_threshold(self):
        """Test similarity threshold is 0.80."""
        from modules.pipeline.nodes.batch_merger import BatchMergerNode

        assert BatchMergerNode.SIMILARITY_THRESHOLD == 0.80
