# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for EmbeddingProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEmbeddingProviderInit:
    """Tests for EmbeddingProvider initialization."""

    def test_init_openai_provider(self):
        """Test initialization with OpenAI-compatible endpoint."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
                model="text-embedding-3-small",
                timeout=30.0,
            )

            mock_openai.assert_called_once()
            assert provider._is_ollama is False
            assert provider._ollama_base_url is None

    def test_init_ollama_provider_with_v1_path(self):
        """Test initialization with Ollama endpoint (with /v1 path)."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            # Should detect Ollama and set up native endpoint
            assert provider._is_ollama is True
            assert provider._ollama_base_url == "http://localhost:11434"

    def test_init_ollama_provider_without_v1_path(self):
        """Test initialization with Ollama endpoint (without /v1 path)."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434",
                model="nomic-embed-text",
            )

            assert provider._is_ollama is True
            assert provider._ollama_base_url == "http://localhost:11434"

    def test_init_ollama_detected_by_port(self):
        """Test Ollama detection by port number."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://custom-host:11434/some/path",
                model="custom-model",
            )

            assert provider._is_ollama is True

    def test_init_custom_model(self):
        """Test initialization with custom model."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
                model="custom-embedding-model",
            )

            assert provider._model == "custom-embedding-model"


class TestEmbeddingProviderChat:
    """Tests for EmbeddingProvider.chat method."""

    def test_chat_raises_not_implemented(self):
        """Test that chat() raises NotImplementedError."""
        with patch("core.llm.providers.embedding.AsyncOpenAI"):
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            with pytest.raises(NotImplementedError) as exc_info:
                import asyncio

                asyncio.run(provider.chat("system", "user"))

            assert "Use ChatProvider" in str(exc_info.value)


class TestEmbeddingProviderEmbed:
    """Tests for EmbeddingProvider.embed method."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider instance."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_embeddings = MagicMock()
            mock_embeddings.data = [
                MagicMock(embedding=[0.1, 0.2, 0.3]),
                MagicMock(embedding=[0.4, 0.5, 0.6]),
            ]
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_embeddings)
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )
            return provider

    @pytest.mark.asyncio
    async def test_embed_openai_provider(self, provider):
        """Test embed() with OpenAI provider."""
        texts = ["Hello world", "Test embedding"]
        result = await provider.embed(texts)

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_uses_client_embeddings_create(self, provider):
        """Test that embed() calls client's embeddings.create."""
        texts = ["text1", "text2"]
        await provider.embed(texts)

        provider._client.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_ollama_native_endpoint(self):
        """Test embed() with Ollama native endpoint."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            # Mock httpx.AsyncClient at the module level where it's imported
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
                mock_response.raise_for_status = MagicMock()

                mock_async_client = MagicMock()
                mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
                mock_async_client.__aexit__ = AsyncMock(return_value=None)
                mock_async_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_async_client

                texts = ["test text"]
                result = await provider.embed(texts)

                assert len(result) == 1
                assert result[0] == [0.1, 0.2, 0.3]
                # Verify Ollama native endpoint was called
                mock_async_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_multiple_texts_ollama(self):
        """Test embed() with multiple texts for Ollama."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            with patch("httpx.AsyncClient") as mock_client_class:
                # Create different responses for each call
                responses = [
                    MagicMock(json=lambda: {"embedding": [0.1, 0.2]}, raise_for_status=MagicMock()),
                    MagicMock(json=lambda: {"embedding": [0.3, 0.4]}, raise_for_status=MagicMock()),
                    MagicMock(json=lambda: {"embedding": [0.5, 0.6]}, raise_for_status=MagicMock()),
                ]

                mock_async_client = MagicMock()
                mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
                mock_async_client.__aexit__ = AsyncMock(return_value=None)
                mock_async_client.post = AsyncMock(side_effect=responses)
                mock_client_class.return_value = mock_async_client

                texts = ["text1", "text2", "text3"]
                result = await provider.embed(texts)

                assert len(result) == 3
                assert result[0] == [0.1, 0.2]
                assert result[1] == [0.3, 0.4]
                assert result[2] == [0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_model_override_openai(self, provider):
        """Test embed() with model override."""
        texts = ["test"]
        await provider.embed(texts, model="override-model")

        # Check the call was made with the override model
        call_kwargs = provider._client.embeddings.create.call_args[1]
        assert call_kwargs["model"] == "override-model"

    @pytest.mark.asyncio
    async def test_embed_model_override_ollama(self):
        """Test embed() with model override for Ollama."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="default-model",
            )

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.json.return_value = {"embedding": [0.1, 0.2]}
                mock_response.raise_for_status = MagicMock()

                mock_async_client = MagicMock()
                mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
                mock_async_client.__aexit__ = AsyncMock(return_value=None)
                mock_async_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_async_client

                await provider.embed(["test"], model="override-model")

                # Check that override model was used in the request
                call_args = mock_async_client.post.call_args
                assert call_args[1]["json"]["model"] == "override-model"


class TestEmbeddingProviderEmbedQuery:
    """Tests for EmbeddingProvider.embed_query method."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider instance."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_embeddings = MagicMock()
            mock_embeddings.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_embeddings)
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )
            return provider

    @pytest.mark.asyncio
    async def test_embed_query(self, provider):
        """Test embed_query() method."""
        result = await provider.embed_query("search query")

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_query_empty_string(self, provider):
        """Test embed_query() with empty string."""
        result = await provider.embed_query("")

        # Should return the embedding
        assert result == [0.1, 0.2, 0.3]


class TestEmbeddingProviderClose:
    """Tests for EmbeddingProvider.close method."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider instance."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_openai.return_value = mock_client

            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )
            return provider

    @pytest.mark.asyncio
    async def test_close_no_error(self, provider):
        """Test close() does not raise errors."""
        # Should not raise any exception
        await provider.close()
        provider._client.close.assert_called_once()


class TestEmbeddingProviderEdgeCases:
    """Tests for edge cases in EmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_embed_empty_list(self):
        """Test embed() with empty list."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_embeddings = MagicMock()
            mock_embeddings.data = []
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_embeddings)
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            result = await provider.embed([])
            assert result == []

    @pytest.mark.asyncio
    async def test_embed_single_text(self):
        """Test embed() with single text."""
        with patch("core.llm.providers.embedding.AsyncOpenAI") as mock_openai:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_client = MagicMock()
            mock_embeddings = MagicMock()
            mock_embeddings.data = [MagicMock(embedding=[0.1, 0.2])]
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_embeddings)
            mock_openai.return_value = mock_client

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            result = await provider.embed(["single text"])
            assert len(result) == 1
