# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMCallResult adapter in ProviderPool and QueueManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.label import Label
from core.llm.provider_pool import PoolTask, ProviderPool
from core.llm.queue_manager import ProviderQueue
from core.llm.registry import ProviderInstanceConfig
from core.llm.request import LLMCallResult, LLMRequest, LLMResponse, TokenUsage
from core.llm.types import CallPoint, LLMTask, LLMType


class TestLLMCallResult:
    """Tests for LLMCallResult data structure."""

    def test_token_usage_auto_calculation(self):
        """Test total_tokens is auto-calculated."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_token_usage_explicit_total(self):
        """Test explicit total_tokens is preserved."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=200)
        assert usage.total_tokens == 200

    def test_llm_call_result_creation(self):
        """Test creating LLMCallResult."""
        usage = TokenUsage(input_tokens=10, output_tokens=20)
        result = LLMCallResult(content="Hello", token_usage=usage)
        assert result.content == "Hello"
        assert result.token_usage.input_tokens == 10
        assert result.token_usage.output_tokens == 20
        assert result.token_usage.total_tokens == 30

    def test_llm_call_result_without_token_usage(self):
        """Test LLMCallResult without token usage."""
        result = LLMCallResult(content="Hello")
        assert result.content == "Hello"
        assert result.token_usage is None

    def test_llm_call_result_with_embedding_content(self):
        """Test LLMCallResult with embedding content."""
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        result = LLMCallResult(content=embeddings)
        assert result.content == embeddings
        assert isinstance(result.content, list)

    def test_llm_call_result_with_rerank_content(self):
        """Test LLMCallResult with rerank content."""
        rerank_results = [{"index": 0, "score": 0.95}, {"index": 1, "score": 0.85}]
        result = LLMCallResult(content=rerank_results)
        assert result.content == rerank_results


class TestProviderPoolAdapter:
    """Tests for ProviderPool LLMCallResult adaptation."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock LLM provider that returns LLMCallResult."""
        provider = MagicMock()
        provider.chat = AsyncMock()
        provider.embed = AsyncMock()
        provider.rerank = AsyncMock()
        return provider

    @pytest.fixture
    def provider_config(self):
        """Create provider instance config."""
        return ProviderInstanceConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4o",
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            concurrency=2,
        )

    @pytest.fixture
    def provider_pool(self, provider_config, mock_provider):
        """Create a ProviderPool instance."""
        pool = ProviderPool(
            config=provider_config,
            provider=mock_provider,
        )
        return pool

    def _make_chat_request(self, content: str = "test response"):
        """Create a mock LLMRequest for chat."""
        label = Label(
            llm_type=LLMType.CHAT,
            provider="test-provider",
            model="gpt-4o",
        )
        return LLMRequest(
            label=label,
            payload={
                "system_prompt": "You are helpful.",
                "user_content": "Hello",
            },
        )

    @pytest.mark.asyncio
    async def test_dispatch_to_provider_returns_llm_call_result(self, provider_pool, mock_provider):
        """Test _dispatch_to_provider returns LLMCallResult for chat."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Hello, world!",
            token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

        request = self._make_chat_request()
        result = await provider_pool._dispatch_to_provider(request)

        assert isinstance(result, LLMCallResult)
        assert result.content == "Hello, world!"
        assert result.token_usage.total_tokens == 15

        # Verify provider.chat was called correctly
        mock_provider.chat.assert_called_once_with(
            system_prompt="You are helpful.",
            user_content="Hello",
            model="gpt-4o",
            temperature=0.0,
            max_tokens=None,
        )

    @pytest.mark.asyncio
    async def test_dispatch_to_provider_embedding_wraps_result(self, provider_pool, mock_provider):
        """Test _dispatch_to_provider wraps embedding result in LLMCallResult."""
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_provider.embed.return_value = embeddings

        label = Label(
            llm_type=LLMType.EMBEDDING,
            provider="test-provider",
            model="text-embedding-3-small",
        )
        request = LLMRequest(
            label=label,
            payload={"texts": ["Hello", "World"]},
        )

        result = await provider_pool._dispatch_to_provider(request)

        assert isinstance(result, LLMCallResult)
        assert result.content == embeddings
        assert result.token_usage is None  # Embedding doesn't return token usage

    @pytest.mark.asyncio
    async def test_dispatch_to_provider_rerank_wraps_result(self, provider_pool, mock_provider):
        """Test _dispatch_to_provider wraps rerank result in LLMCallResult."""
        rerank_results = [{"index": 0, "score": 0.95}, {"index": 1, "score": 0.85}]
        mock_provider.rerank.return_value = rerank_results

        label = Label(
            llm_type=LLMType.RERANK,
            provider="test-provider",
            model="jina-reranker-v2",
        )
        request = LLMRequest(
            label=label,
            payload={
                "query": "test query",
                "documents": ["doc1", "doc2"],
                "top_n": 2,
            },
        )

        result = await provider_pool._dispatch_to_provider(request)

        assert isinstance(result, LLMCallResult)
        assert result.content == rerank_results
        assert result.token_usage is None

    @pytest.mark.asyncio
    async def test_execute_task_extracts_content_and_tokens(self, provider_pool, mock_provider):
        """Test _execute_task extracts content and token_usage from LLMCallResult."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Hello, world!",
            token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

        request = self._make_chat_request()
        task = PoolTask(request=request, future=asyncio.get_running_loop().create_future())

        response = await provider_pool._execute_task(task)

        assert isinstance(response, LLMResponse)
        assert response.content == "Hello, world!"
        assert response.tokens_used == 15  # total_tokens
        assert response.success is True
        assert response.attempt == 0

    @pytest.mark.asyncio
    async def test_execute_task_handles_missing_token_usage(self, provider_pool, mock_provider):
        """Test _execute_task handles LLMCallResult without token_usage."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Hello, world!",
            token_usage=None,
        )

        request = self._make_chat_request()
        task = PoolTask(request=request, future=asyncio.get_running_loop().create_future())

        response = await provider_pool._execute_task(task)

        assert response.content == "Hello, world!"
        assert response.tokens_used is None

    @pytest.mark.asyncio
    async def test_execute_task_records_metrics_on_success(self, provider_pool, mock_provider):
        """Test _execute_task records success metrics."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Hello!",
            token_usage=TokenUsage(input_tokens=5, output_tokens=2),
        )

        request = self._make_chat_request()
        task = PoolTask(request=request, future=asyncio.get_running_loop().create_future())

        await provider_pool._execute_task(task)

        metrics = provider_pool.get_metrics()
        assert metrics.successful_requests == 1
        assert metrics.total_requests == 1
        assert metrics.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_execute_task_records_metrics_on_failure(self, provider_pool, mock_provider):
        """Test _execute_task records failure metrics."""
        mock_provider.chat.side_effect = TimeoutError("Request timed out")

        request = self._make_chat_request()
        task = PoolTask(request=request, future=asyncio.get_running_loop().create_future())

        with pytest.raises(TimeoutError):
            await provider_pool._execute_task(task)

        metrics = provider_pool.get_metrics()
        assert metrics.failed_requests == 1
        assert metrics.total_requests == 1
        assert metrics.success_rate == 0.0
        assert metrics.last_error == "Request timed out"


class TestProviderQueueAdapter:
    """Tests for ProviderQueue LLMCallResult adaptation."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock LLM provider."""
        provider = MagicMock()
        provider.chat = AsyncMock()
        return provider

    @pytest.fixture
    def provider_queue(self, mock_provider):
        """Create a ProviderQueue instance."""
        return ProviderQueue(
            provider_name="test-provider",
            concurrency=2,
            provider=mock_provider,
            model="gpt-4o",
        )

    def _make_llm_task(self):
        """Create a mock LLMTask."""
        return LLMTask(
            call_point=CallPoint.ENTITY_EXTRACTOR,
            llm_type=LLMType.CHAT,
            payload={
                "system_prompt": "Extract entities.",
                "user_content": "Apple is a company.",
            },
            priority=1,
        )

    @pytest.mark.asyncio
    async def test_dispatch_extracts_content_from_llm_call_result(
        self, provider_queue, mock_provider
    ):
        """Test _dispatch extracts content from LLMCallResult."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Entities: Apple",
            token_usage=TokenUsage(input_tokens=20, output_tokens=5),
        )

        task = self._make_llm_task()
        result = await provider_queue._dispatch(task)

        assert result == "Entities: Apple"
        mock_provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_handles_embedding_result(self, provider_queue, mock_provider):
        """Test _dispatch handles embedding result."""
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        # 注意：当前 _dispatch 只调用 chat，这个测试验证未来的扩展性
        # 如果需要支持 embedding，需要修改 _dispatch 方法

    @pytest.mark.asyncio
    async def test_dispatch_handles_missing_token_usage(self, provider_queue, mock_provider):
        """Test _dispatch handles missing token_usage."""
        mock_provider.chat.return_value = LLMCallResult(
            content="Response without token count",
            token_usage=None,
        )

        task = self._make_llm_task()
        result = await provider_queue._dispatch(task)

        assert result == "Response without token count"

    @pytest.mark.asyncio
    async def test_dispatch_converts_non_string_content(self, provider_queue, mock_provider):
        """Test _dispatch converts non-string content to string."""
        # 模拟返回 dict 内容的情况
        mock_provider.chat.return_value = LLMCallResult(
            content={"entities": ["Apple", "Google"]},
            token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

        task = self._make_llm_task()
        result = await provider_queue._dispatch(task)

        # 应该转换为字符串
        assert "Apple" in result
        assert "Google" in result


class TestLLMResponseTokenUsage:
    """Tests for LLMResponse tokens_used field."""

    def test_tokens_used_default_none(self):
        """Test tokens_used defaults to None."""
        label = Label(llm_type=LLMType.CHAT, provider="test", model="model")
        response = LLMResponse(
            content="Hello",
            label=label,
            latency_ms=100.0,
        )
        assert response.tokens_used is None

    def test_tokens_used_can_be_set(self):
        """Test tokens_used can be set."""
        label = Label(llm_type=LLMType.CHAT, provider="test", model="model")
        response = LLMResponse(
            content="Hello",
            label=label,
            latency_ms=100.0,
            tokens_used=150,
        )
        assert response.tokens_used == 150

    def test_success_property(self):
        """Test success property."""
        label = Label(llm_type=LLMType.CHAT, provider="test", model="model")

        success_response = LLMResponse(
            content="Hello",
            label=label,
            latency_ms=100.0,
        )
        assert success_response.success is True

        failed_response = LLMResponse(
            content="",
            label=label,
            latency_ms=100.0,
            error=TimeoutError("Timeout"),
        )
        assert failed_response.success is False


# Import asyncio for the tests
import asyncio
