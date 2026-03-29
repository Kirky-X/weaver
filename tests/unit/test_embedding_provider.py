# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for EmbeddingProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEmbeddingProviderInit:
    """Tests for EmbeddingProvider initialization."""

    def test_init_openai_provider(self):
        """Test initialization with OpenAI-compatible endpoint."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
                model="text-embedding-3-small",
                timeout=30.0,
            )

            mock_embeddings.assert_called_once()
            assert provider._is_ollama is False
            assert provider._ollama_endpoint is None

    def test_init_ollama_provider_with_v1_path(self):
        """Test initialization with Ollama endpoint (with /v1 path)."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            # Should detect Ollama and set up native endpoint
            assert provider._is_ollama is True
            assert provider._ollama_endpoint == "http://localhost:11434/api/embeddings"

    def test_init_ollama_provider_without_v1_path(self):
        """Test initialization with Ollama endpoint (without /v1 path)."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434",
                model="nomic-embed-text",
            )

            assert provider._is_ollama is True
            assert provider._ollama_endpoint == "http://localhost:11434/api/embeddings"

    def test_init_ollama_detected_by_port(self):
        """Test Ollama detection by port number."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://custom-host:11434/some/path",
                model="custom-model",
            )

            assert provider._is_ollama is True

    def test_init_custom_model(self):
        """Test initialization with custom model."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
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
        with patch("core.llm.providers.embedding.OpenAIEmbeddings"):
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
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_instance.aembed_documents = AsyncMock(
                return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            )
            mock_embeddings.return_value = mock_instance

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

        # embed() 返回 LLMCallResult
        assert hasattr(result, "content")
        assert hasattr(result, "token_usage")
        assert len(result.content) == 2
        assert result.content[0] == [0.1, 0.2, 0.3]
        assert result.content[1] == [0.4, 0.5, 0.6]
        assert result.token_usage is not None

    @pytest.mark.asyncio
    async def test_embed_uses_client_aembed_documents(self, provider):
        """Test that embed() calls client's aembed_documents."""
        texts = ["text1", "text2"]
        await provider.embed(texts)

        provider._client.aembed_documents.assert_called_once_with(texts)

    @pytest.mark.asyncio
    async def test_embed_ollama_native_endpoint(self):
        """Test embed() with Ollama native endpoint."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_embeddings.return_value = mock_instance

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            # Mock httpx.AsyncClient at the module level where it's imported
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
                mock_response.raise_for_status = MagicMock()

                mock_async_client = MagicMock()
                mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
                mock_async_client.__aexit__ = AsyncMock(return_value=None)
                mock_async_client.post = AsyncMock(return_value=mock_response)
                mock_client.return_value = mock_async_client

                texts = ["test text"]
                result = await provider.embed(texts)

                # embed() 返回 LLMCallResult
                assert hasattr(result, "content")
                assert len(result.content) == 1
                assert result.content[0] == [0.1, 0.2, 0.3]
                # Verify Ollama native endpoint was called
                mock_async_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_multiple_texts_ollama(self):
        """Test embed() with multiple texts for Ollama."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_embeddings.return_value = mock_instance

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="nomic-embed-text",
            )

            with patch("httpx.AsyncClient") as mock_client:
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
                mock_client.return_value = mock_async_client

                texts = ["text1", "text2", "text3"]
                result = await provider.embed(texts)

                # embed() 返回 LLMCallResult
                assert len(result.content) == 3
                assert result.content[0] == [0.1, 0.2]
                assert result.content[1] == [0.3, 0.4]
                assert result.content[2] == [0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_model_override_openai(self, provider):
        """Test embed() with model override (OpenAI ignores it)."""
        texts = ["test"]
        await provider.embed(texts, model="override-model")

        # Model override is not supported by LangChain, so it's ignored
        provider._client.aembed_documents.assert_called_once_with(texts)

    @pytest.mark.asyncio
    async def test_embed_model_override_ollama(self):
        """Test embed() with model override for Ollama."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_embeddings.return_value = mock_instance

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="http://localhost:11434/v1",
                model="default-model",
            )

            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = {"embedding": [0.1, 0.2]}
                mock_response.raise_for_status = MagicMock()

                mock_async_client = MagicMock()
                mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
                mock_async_client.__aexit__ = AsyncMock(return_value=None)
                mock_async_client.post = AsyncMock(return_value=mock_response)
                mock_client.return_value = mock_async_client

                await provider.embed(["test"], model="override-model")

                # Check that override model was used in the request
                call_args = mock_async_client.post.call_args
                assert call_args[1]["json"]["model"] == "override-model"


class TestEmbeddingProviderEmbedQuery:
    """Tests for EmbeddingProvider.embed_query method."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider instance."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_instance.aembed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
            mock_embeddings.return_value = mock_instance

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
        provider._client.aembed_query.assert_called_once_with("search query")

    @pytest.mark.asyncio
    async def test_embed_query_empty_string(self, provider):
        """Test embed_query() with empty string."""
        result = await provider.embed_query("")

        provider._client.aembed_query.assert_called_once_with("")


class TestEmbeddingProviderClose:
    """Tests for EmbeddingProvider.close method."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider instance."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings"):
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


class TestEmbeddingProviderEdgeCases:
    """Tests for edge cases in EmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_embed_empty_list(self):
        """Test embed() with empty list."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_instance.aembed_documents = AsyncMock(return_value=[])
            mock_embeddings.return_value = mock_instance

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            result = await provider.embed([])
            # embed() 返回 LLMCallResult
            assert result.content == []

    @pytest.mark.asyncio
    async def test_embed_single_text(self):
        """Test embed() with single text."""
        with patch("core.llm.providers.embedding.OpenAIEmbeddings") as mock_embeddings:
            from core.llm.providers.embedding import EmbeddingProvider

            mock_instance = MagicMock()
            mock_instance.aembed_documents = AsyncMock(return_value=[[0.1, 0.2]])
            mock_embeddings.return_value = mock_instance

            provider = EmbeddingProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            result = await provider.embed(["single text"])
            # embed() 返回 LLMCallResult
            assert len(result.content) == 1
