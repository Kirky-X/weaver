# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Rerank Provider."""

import pytest

from core.llm.providers.rerank import RerankProvider


class TestRerankProviderInit:
    """Test RerankProvider initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        provider = RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
        )

        assert provider._api_key == "test-api-key"
        assert provider._base_url == "https://api.example.com"
        assert provider._model == ""
        assert provider._timeout == 30.0

    def test_init_with_model(self):
        """Test initialization with model."""
        provider = RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
            model="rerank-model-v1",
        )

        assert provider._model == "rerank-model-v1"

    def test_init_with_timeout(self):
        """Test initialization with custom timeout."""
        provider = RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
            timeout=60.0,
        )

        assert provider._timeout == 60.0

    def test_init_all_params(self):
        """Test initialization with all parameters."""
        provider = RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
            model="rerank-model-v1",
            timeout=45.0,
        )

        assert provider._api_key == "test-api-key"
        assert provider._base_url == "https://api.example.com"
        assert provider._model == "rerank-model-v1"
        assert provider._timeout == 45.0


class TestRerankProviderChat:
    """Test RerankProvider chat method."""

    @pytest.fixture
    def provider(self):
        """Create RerankProvider instance."""
        return RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
        )

    @pytest.mark.asyncio
    async def test_chat_raises_not_implemented(self, provider):
        """Test chat raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Use ChatProvider for chat completions"):
            await provider.chat(
                system_prompt="System",
                user_content="Hello",
            )


class TestRerankProviderEmbed:
    """Test RerankProvider embed method."""

    @pytest.fixture
    def provider(self):
        """Create RerankProvider instance."""
        return RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
        )

    @pytest.mark.asyncio
    async def test_embed_raises_not_implemented(self, provider):
        """Test embed raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Use EmbeddingProvider for embeddings"):
            await provider.embed(["text1", "text2"])


class TestRerankProviderRerank:
    """Test RerankProvider rerank method."""

    @pytest.fixture
    def provider(self):
        """Create RerankProvider instance."""
        return RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
            model="rerank-model-v1",
        )

    @pytest.mark.asyncio
    async def test_rerank_basic(self, provider):
        """Test basic rerank operation."""
        query = "test query"
        documents = ["doc1", "doc2", "doc3"]

        results = await provider.rerank(query, documents)

        assert len(results) == 3
        assert all("index" in r for r in results)
        assert all("score" in r for r in results)

    @pytest.mark.asyncio
    async def test_rerank_with_top_n(self, provider):
        """Test rerank with top_n parameter."""
        query = "test query"
        documents = ["doc1", "doc2", "doc3", "doc4", "doc5"]

        results = await provider.rerank(query, documents, top_n=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_rerank_top_n_greater_than_docs(self, provider):
        """Test rerank when top_n > number of documents."""
        query = "test query"
        documents = ["doc1", "doc2"]

        results = await provider.rerank(query, documents, top_n=10)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self, provider):
        """Test rerank with empty documents list."""
        query = "test query"
        documents = []

        results = await provider.rerank(query, documents)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_rerank_single_document(self, provider):
        """Test rerank with single document."""
        query = "test query"
        documents = ["only doc"]

        results = await provider.rerank(query, documents)

        assert len(results) == 1
        assert results[0]["index"] == 0
        assert results[0]["score"] == 1.0

    @pytest.mark.asyncio
    async def test_rerank_scores_decreasing(self, provider):
        """Test that scores are decreasing (placeholder behavior)."""
        query = "test query"
        documents = ["doc1", "doc2", "doc3"]

        results = await provider.rerank(query, documents)

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_rerank_indices_correct(self, provider):
        """Test that indices match document positions."""
        query = "test query"
        documents = ["doc1", "doc2", "doc3"]

        results = await provider.rerank(query, documents)

        indices = [r["index"] for r in results]
        assert indices == [0, 1, 2]


class TestRerankProviderClose:
    """Test RerankProvider close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        provider = RerankProvider(
            api_key="test-api-key",
            base_url="https://api.example.com",
        )

        await provider.close()
