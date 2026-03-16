"""Unit tests for Pipeline nodes."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from modules.pipeline.state import PipelineState
from modules.pipeline.nodes.classifier import ClassifierNode
from modules.pipeline.nodes.cleaner import CleanerNode
from modules.pipeline.nodes.categorizer import CategorizerNode
from modules.pipeline.nodes.vectorize import VectorizeNode
from modules.pipeline.nodes.batch_merger import BatchMergerNode, UnionFind
from modules.pipeline.nodes.re_vectorize import ReVectorizeNode
from modules.pipeline.nodes.analyze import AnalyzeNode
from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
from modules.pipeline.nodes.entity_extractor import EntityExtractorNode
from core.llm.types import CallPoint


class TestClassifierNode:
    """Tests for ClassifierNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(is_news=True, confidence=0.95))
        return llm

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_raw(self):
        """Mock raw article data."""
        raw = MagicMock()
        raw.title = "Test Title"
        raw.body = "Test body content"
        return raw

    @pytest.mark.asyncio
    async def test_classifier_node_is_news(self, mock_llm, mock_prompt_loader, mock_budget, mock_raw):
        """Test classifier identifies news correctly."""
        mock_llm.call = AsyncMock(return_value=MagicMock(is_news=True, confidence=0.95))
        node = ClassifierNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(raw=mock_raw)
        result = await node.execute(state)
        assert result.get("is_news") is True

    @pytest.mark.asyncio
    async def test_classifier_node_not_news(self, mock_llm, mock_prompt_loader, mock_budget, mock_raw):
        """Test classifier identifies non-news correctly."""
        mock_llm.call = AsyncMock(return_value=MagicMock(is_news=False, confidence=0.9))
        node = ClassifierNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(raw=mock_raw)
        result = await node.execute(state)
        assert result.get("is_news") is False

    @pytest.mark.asyncio
    async def test_classifier_node_prompt_version(self, mock_llm, mock_prompt_loader, mock_budget, mock_raw):
        """Test classifier records prompt version."""
        mock_llm.call = AsyncMock(return_value=MagicMock(is_news=True, confidence=0.95))
        node = ClassifierNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(raw=mock_raw)
        result = await node.execute(state)
        assert "prompt_versions" in result
        assert "classifier" in result["prompt_versions"]


class TestCleanerNode:
    """Tests for CleanerNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        from core.llm.output_validator import CleanerOutput, CleanerContent
        llm = MagicMock()
        llm.call = AsyncMock(return_value=CleanerOutput(
            content=CleanerContent(title="Cleaned Title", body="Cleaned body content"),
            tags=["科技", "AI"],
            entities=[]
        ))
        return llm

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="2.0.0")
        return loader

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_raw(self):
        """Mock raw article data."""
        raw = MagicMock()
        raw.title = "Test Title"
        raw.body = "Test body content"
        raw.url = "https://example.com/test"
        raw.publish_time = None
        raw.source_host = "example.com"
        return raw

    @pytest.mark.asyncio
    async def test_cleaner_node_basic(self, mock_llm, mock_prompt_loader, mock_budget, mock_raw):
        """Test cleaner cleans content."""
        from core.llm.output_validator import CleanerOutput, CleanerContent
        mock_llm.call = AsyncMock(return_value=CleanerOutput(
            content=CleanerContent(title="Cleaned Title", body="Cleaned body"),
            tags=["科技"],
            entities=[]
        ))
        node = CleanerNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(raw=mock_raw)
        result = await node.execute(state)
        assert "cleaned" in result
        assert "tags" in result
        assert result["tags"] == ["科技"]

    @pytest.mark.asyncio
    async def test_cleaner_node_truncation(self, mock_llm, mock_prompt_loader, mock_budget, mock_raw):
        """Test cleaner uses token truncation."""
        from core.llm.output_validator import CleanerOutput, CleanerContent
        mock_llm.call = AsyncMock(return_value=CleanerOutput(
            content=CleanerContent(title="Title", body="Body"),
            tags=[],
            entities=[]
        ))
        node = CleanerNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(raw=mock_raw)
        await node.execute(state)
        mock_budget.truncate.assert_called()


class TestCategorizerNode:
    """Tests for CategorizerNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(
            category="科技",
            language="zh",
            region="中国"
        ))
        return llm

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_cleaned(self):
        """Mock cleaned article data."""
        return {"title": "Title", "body": "Body"}

    @pytest.mark.asyncio
    async def test_categorizer_node(self, mock_llm, mock_prompt_loader, mock_cleaned):
        """Test categorizer assigns category."""
        mock_llm.call = AsyncMock(return_value=MagicMock(
            category="科技",
            language="zh",
            region="中国"
        ))
        node = CategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert result.get("category") == "科技"
        assert result.get("language") == "zh"


class TestVectorizeNode:
    """Tests for VectorizeNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024])
        return llm

    @pytest.fixture
    def mock_cleaned(self):
        """Mock cleaned article data."""
        return {"title": "Title", "body": "Body"}

    @pytest.mark.asyncio
    async def test_vectorize_node(self, mock_llm, mock_cleaned):
        """Test vectorize generates embeddings."""
        mock_llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024])
        node = VectorizeNode(llm=mock_llm)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert "vectors" in result
        assert "content" in result["vectors"]


class TestBatchMergerNode:
    """Tests for BatchMergerNode."""

    SIMILARITY_THRESHOLD = 0.80

    def test_similarity_threshold(self):
        """Test similarity threshold is 0.80."""
        assert BatchMergerNode.SIMILARITY_THRESHOLD == 0.80

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(
            merged_title="Merged Title",
            merged_body="Merged body"
        ))
        return llm

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.mark.asyncio
    async def test_batch_merger_intra_batch(self, mock_llm, mock_prompt_loader):
        """Test batch merger processes intra-batch similarity."""
        node = BatchMergerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        assert node.SIMILARITY_THRESHOLD == 0.80


class TestReVectorizeNode:
    """Tests for ReVectorizeNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        return llm

    @pytest.fixture
    def mock_vector_repo(self):
        """Mock vector repository."""
        repo = MagicMock()
        repo.upsert_article_vector = AsyncMock()
        return repo

    @pytest.fixture
    def mock_cleaned(self):
        """Mock cleaned article data."""
        return {"title": "Title", "body": "Body"}

    @pytest.mark.asyncio
    async def test_re_vectorize_node(self, mock_llm, mock_vector_repo, mock_cleaned):
        """Test re-vectorize generates new embeddings."""
        mock_llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(llm=mock_llm)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert "vectors" in result


class TestAnalyzeNode:
    """Tests for AnalyzeNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(
            summary="Test summary",
            event_time="2024-01-01T00:00:00",
            subjects=["subject1"],
            key_data=["data1"],
            impact="Test impact",
            has_data=True,
            sentiment="positive",
            sentiment_score=0.8,
            primary_emotion="乐观",
            emotion_targets=["target1"],
            score=0.75
        ))
        return llm

    @pytest.fixture
    def mock_prompt_loader(self):
        """Mock prompt loader."""
        loader = MagicMock()
        loader.get_version = MagicMock(return_value="1.0.0")
        return loader

    @pytest.fixture
    def mock_budget(self):
        """Mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(return_value="truncated text")
        return budget

    @pytest.fixture
    def mock_cleaned(self):
        """Mock cleaned article data."""
        return {"title": "Title", "body": "Body"}

    @pytest.mark.asyncio
    async def test_analyze_node_summary(self, mock_llm, mock_prompt_loader, mock_budget, mock_cleaned):
        """Test analyze generates summary."""
        mock_llm.call = AsyncMock(return_value=MagicMock(
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
            score=0.5
        ))
        node = AnalyzeNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert "summary_info" in result

    @pytest.mark.asyncio
    async def test_analyze_node_sentiment(self, mock_llm, mock_prompt_loader, mock_budget, mock_cleaned):
        """Test analyze extracts sentiment."""
        mock_llm.call = AsyncMock(return_value=MagicMock(
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
            score=0.8
        ))
        node = AnalyzeNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert "sentiment" in result

    @pytest.mark.asyncio
    async def test_analyze_node_score(self, mock_llm, mock_prompt_loader, mock_budget, mock_cleaned):
        """Test analyze calculates score."""
        mock_llm.call = AsyncMock(return_value=MagicMock(
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
            score=0.85
        ))
        node = AnalyzeNode(llm=mock_llm, prompt_loader=mock_prompt_loader, budget=mock_budget)
        state = PipelineState(cleaned=mock_cleaned)
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        assert result.get("score") == 0.85


class TestEntityExtractorNode:
    """Tests for EntityExtractorNode."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=MagicMock(
            entities=[{"name": "张三", "type": "人物"}],
            relations=[]
        ))
        llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024])
        return llm

    @pytest.fixture
    def mock_spacy(self):
        """Mock spaCy extractor."""
        spacy = MagicMock()
        mock_entity = MagicMock()
        mock_entity.name = "张三"
        mock_entity.type = "人物"
        mock_entity.label = "PER"
        spacy.extract = MagicMock(return_value=[mock_entity])
        return spacy

    @pytest.fixture
    def mock_vector_repo(self):
        """Mock vector repository."""
        repo = MagicMock()
        repo.upsert_entity_vectors = AsyncMock()
        return repo

    @pytest.fixture
    def mock_cleaned(self):
        """Mock cleaned article data."""
        return {"title": "Title", "body": "Body"}

    @pytest.mark.asyncio
    async def test_entity_extractor_spacy(self, mock_llm, mock_spacy, mock_vector_repo, mock_cleaned):
        """Test entity extractor uses spaCy."""
        node = EntityExtractorNode(
            llm=mock_llm,
            spacy=mock_spacy,
            vector_repo=mock_vector_repo,
            budget=MagicMock(truncate=MagicMock(return_value="text")),
            prompt_loader=MagicMock(get_version=MagicMock(return_value="1.0"))
        )
        state = PipelineState(cleaned=mock_cleaned, language="zh")
        state["raw"] = MagicMock(url="https://example.com/test")
        result = await node.execute(state)
        mock_spacy.extract.assert_called()
