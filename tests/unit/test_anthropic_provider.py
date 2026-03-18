# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Anthropic Provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.providers.anthropic import AnthropicProvider


class TestAnthropicProviderInit:
    """Test AnthropicProvider initialization."""

    def test_init(self):
        """Test basic initialization."""
        with patch("core.llm.providers.anthropic.ChatAnthropic") as mock_chat:
            provider = AnthropicProvider(
                api_key="test-key",
                base_url="http://127.0.0.1:5000",
                model="claude-sonnet-4-20250514",
                timeout=300.0,
            )

            mock_chat.assert_called_once_with(
                api_key="test-key",
                anthropic_api_url="http://127.0.0.1:5000",
                model="claude-sonnet-4-20250514",
                timeout=300.0,
                max_retries=0,
            )
            assert provider._default_model == "claude-sonnet-4-20250514"
            assert provider._base_url == "http://127.0.0.1:5000"


class TestAnthropicProviderChat:
    """Test AnthropicProvider.chat method."""

    @pytest.fixture
    def mock_client(self):
        """Create mock ChatAnthropic client."""
        client = MagicMock()
        client.ainvoke = AsyncMock()
        return client

    @pytest.fixture
    def provider(self, mock_client):
        """Create AnthropicProvider with mocked client."""
        with patch("core.llm.providers.anthropic.ChatAnthropic", return_value=mock_client):
            provider = AnthropicProvider(
                api_key="test-key",
                base_url="http://127.0.0.1:5000",
                model="claude-sonnet-4-20250514",
            )
            provider._client = mock_client
            return provider

    @pytest.mark.asyncio
    async def test_chat_basic(self, provider, mock_client):
        """Test basic chat request."""
        mock_response = MagicMock()
        mock_response.content = "Hello, I'm Claude!"
        mock_client.ainvoke.return_value = mock_response

        result = await provider.chat(
            system_prompt="You are a helpful assistant.",
            user_content="Hello!",
        )

        assert result == "Hello, I'm Claude!"
        mock_client.ainvoke.assert_called_once()

        call_args = mock_client.ainvoke.call_args
        messages = call_args.args[0]
        assert len(messages) == 2
        assert messages[0].content == "You are a helpful assistant."
        assert messages[1].content == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_with_temperature(self, provider, mock_client):
        """Test chat with temperature parameter."""
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_client.ainvoke.return_value = mock_response

        await provider.chat(
            system_prompt="System",
            user_content="User",
            temperature=0.7,
        )

        call_kwargs = mock_client.ainvoke.call_args.kwargs
        assert call_kwargs.get("temperature") == 0.7

    @pytest.mark.asyncio
    async def test_chat_with_max_tokens(self, provider, mock_client):
        """Test chat with max_tokens parameter."""
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_client.ainvoke.return_value = mock_response

        await provider.chat(
            system_prompt="System",
            user_content="User",
            max_tokens=1000,
        )

        call_kwargs = mock_client.ainvoke.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 1000

    @pytest.mark.asyncio
    async def test_chat_with_model_override(self, provider, mock_client):
        """Test chat with model override."""
        mock_bound_client = MagicMock()
        mock_bound_client.ainvoke = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_bound_client.ainvoke.return_value = mock_response

        mock_client.bind.return_value = mock_bound_client

        await provider.chat(
            system_prompt="System",
            user_content="User",
            model="claude-opus-4",
        )

        mock_client.bind.assert_called_once_with(model="claude-opus-4")


class TestAnthropicProviderEmbed:
    """Test AnthropicProvider.embed method."""

    def test_embed_not_implemented(self):
        """Test that embed raises NotImplementedError."""
        with patch("core.llm.providers.anthropic.ChatAnthropic"):
            provider = AnthropicProvider(
                api_key="test-key",
                base_url="http://127.0.0.1:5000",
            )

            with pytest.raises(NotImplementedError) as exc_info:
                import asyncio

                asyncio.run(provider.embed(["test"]))

            assert "EmbeddingProvider" in str(exc_info.value)


class TestAnthropicProviderClose:
    """Test AnthropicProvider.close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        with patch("core.llm.providers.anthropic.ChatAnthropic"):
            provider = AnthropicProvider(
                api_key="test-key",
                base_url="http://127.0.0.1:5000",
            )

            await provider.close()
