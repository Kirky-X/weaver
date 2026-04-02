# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLM client integration."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.llm import Label, LLMClient, LLMType
from core.llm.config import LLMConfigLoader


@pytest.fixture
def test_config(tmp_path: Path) -> Path:
    """Create test config file."""
    config_content = """
[global]
circuit_breaker_threshold = 3
circuit_breaker_timeout = 30.0

[providers.aiping]
type = "openai"
base_url = "https://www.aiping.cn/api/v1"
api_key = "${AIPING_API_KEY}"
rpm_limit = 100
concurrency = 5
timeout = 120.0

  [providers.aiping.models.chat]
  model_id = "GLM-4-9B-0414"
  temperature = 0.0
  max_tokens = 4096
  capabilities = ["chat"]

  [providers.aiping.models.embedding]
  model_id = "Qwen3-Embedding-0.6B"
  capabilities = ["embedding"]

  [providers.aiping.models.rerank]
  model_id = "Qwen3-Reranker-0.6B"
  capabilities = ["rerank"]

[defaults.chat]
label = "chat.aiping.GLM-4-9B-0414"
fallbacks = []

[defaults.embedding]
label = "embedding.aiping.Qwen3-Embedding-0.6B"
fallbacks = []

[defaults.rerank]
label = "rerank.aiping.Qwen3-Reranker-0.6B"
fallbacks = []

[call-points.classifier]
primary = "chat.aiping.GLM-4-9B-0414"
fallbacks = []

[call-points.embedding]
primary = "embedding.aiping.Qwen3-Embedding-0.6B"
fallbacks = []

[call-points.rerank]
primary = "rerank.aiping.Qwen3-Reranker-0.6B"
fallbacks = []
"""
    config_file = tmp_path / "llm.toml"
    config_file.write_text(config_content)
    return config_file


class TestLLMClientInit:
    """Tests for LLMClient initialization."""

    @pytest.mark.asyncio
    async def test_create_from_config(self, test_config: Path) -> None:
        """Test creating client from config file."""
        with patch.dict(os.environ, {"AIPING_API_KEY": "test-key"}):
            client = await LLMClient.create_from_config(str(test_config))
            assert client is not None
            assert "aiping" in client.list_providers()

    @pytest.mark.asyncio
    async def test_list_providers(self, test_config: Path) -> None:
        """Test listing providers."""
        with patch.dict(os.environ, {"AIPING_API_KEY": "test-key"}):
            client = await LLMClient.create_from_config(str(test_config))
            providers = client.list_providers()
            assert len(providers) == 1
            assert "aiping" in providers

    @pytest.mark.asyncio
    async def test_get_metrics(self, test_config: Path) -> None:
        """Test getting metrics."""
        with patch.dict(os.environ, {"AIPING_API_KEY": "test-key"}):
            client = await LLMClient.create_from_config(str(test_config))
            metrics = client.get_metrics()
            assert "aiping" in metrics


@pytest.mark.skipif(
    not os.environ.get("WEAVER_LLM__PROVIDERS__AIPING__API_KEY"),
    reason="WEAVER_LLM__PROVIDERS__AIPING__API_KEY not set",
)
class TestLLMClientLive:
    """Live tests requiring actual API key."""

    @pytest.mark.asyncio
    async def test_chat_call(self, test_config: Path) -> None:
        """Test live chat call."""
        client = await LLMClient.create_from_config(str(test_config))

        response = await client.call(
            "chat.aiping.GLM-4-9B-0414",
            {
                "system_prompt": "You are a helpful assistant.",
                "user_content": "Say 'hello' in one word.",
            },
        )

        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_embedding_call(self, test_config: Path) -> None:
        """Test live embedding call."""
        client = await LLMClient.create_from_config(str(test_config))

        embeddings = await client.embed_default(["hello world"])

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1
        assert isinstance(embeddings[0], list)
        assert len(embeddings[0]) > 0  # Has dimensions

    @pytest.mark.asyncio
    async def test_rerank_call(self, test_config: Path) -> None:
        """Test live rerank call."""
        client = await LLMClient.create_from_config(str(test_config))

        results = await client.rerank_default(
            query="What is Python?",
            documents=[
                "Python is a programming language.",
                "Java is also a programming language.",
                "The sky is blue.",
            ],
            top_n=2,
        )

        assert isinstance(results, list)
        assert len(results) == 2
        assert "index" in results[0]
        assert "score" in results[0]

    @pytest.mark.asyncio
    async def test_call_at(self, test_config: Path) -> None:
        """Test call_at method."""
        client = await LLMClient.create_from_config(str(test_config))

        response = await client.call_at(
            "classifier",
            {
                "system_prompt": "Classify the text.",
                "user_content": "Hello world",
            },
        )

        assert isinstance(response, str)
