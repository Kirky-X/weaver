# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Embedding LLM provider using LangChain's OpenAIEmbeddings."""

from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings

from core.llm.providers.base import BaseLLMProvider
from core.llm.request import LLMCallResult, TokenUsage
from core.observability.logging import get_logger

log = get_logger("embedding_provider")


class EmbeddingProvider(BaseLLMProvider):
    """OpenAI-compatible embedding provider using LangChain."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-3-large",
        timeout: float = 30.0,
    ) -> None:
        self._model = model

        # Check if this is an Ollama endpoint
        is_ollama = "ollama" in base_url.lower() or "11434" in base_url

        if is_ollama:
            # For Ollama, use the native /api/embeddings endpoint
            # Map /v1 base URL to /api for embeddings
            ollama_base_url = base_url.replace("/v1", "") if "/v1" in base_url else base_url

            # Override to use Ollama's native API
            self._client = OpenAIEmbeddings(
                api_key=api_key,
                base_url=f"{ollama_base_url}/v1",  # Keep /v1 for OpenAI compatibility
                model=model,
                timeout=timeout,
            )
            # Store the actual endpoint for direct calls
            self._ollama_endpoint = f"{ollama_base_url}/api/embeddings"
            self._is_ollama = True
        else:
            self._client = OpenAIEmbeddings(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
            )
            self._is_ollama = False
            self._ollama_endpoint = None

    async def chat(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Not implemented for embedding provider.

        Raises:
            NotImplementedError: Embedding provider does not support chat.
        """
        raise NotImplementedError("Use ChatProvider for chat completions")

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> LLMCallResult:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of input texts.
            model: Optional model override (not supported by LangChain).

        Returns:
            LLMCallResult with embedding vectors and token usage.
        """
        import httpx

        embeddings: list[list[float]] = []
        token_usage = TokenUsage()

        if self._is_ollama and self._ollama_endpoint:
            # Use Ollama's native /api/embeddings endpoint
            async with httpx.AsyncClient(timeout=60.0) as client:
                for text in texts:
                    response = await client.post(
                        self._ollama_endpoint,
                        json={"model": model or self._model, "prompt": text},
                    )
                    response.raise_for_status()
                    data: dict[str, Any] = response.json()
                    embeddings.append(data["embedding"])

                    # Ollama 可能返回 prompt_eval_count
                    if "prompt_eval_count" in data:
                        token_usage.input_tokens += data["prompt_eval_count"]
        else:
            # LangChain OpenAI embeddings - 不直接返回 token 用量
            # 需要通过原始 API 调用获取，这里简化处理
            embeddings = await self._client.aembed_documents(texts)

            # 估算 token 数量（简化：假设平均每词约 1.3 tokens）
            total_chars = sum(len(t) for t in texts)
            estimated_tokens = int(total_chars / 4)  # 粗略估算
            token_usage.input_tokens = estimated_tokens

        return LLMCallResult(
            content=embeddings,
            token_usage=token_usage,
        )

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query text.

        Args:
            text: Input text.

        Returns:
            Embedding vector.
        """
        return await self._client.aembed_query(text)

    async def close(self) -> None:
        """Clean up resources.

        No explicit cleanup needed for OpenAI embedding client.
        """
