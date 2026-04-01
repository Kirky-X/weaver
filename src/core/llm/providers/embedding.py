# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Embedding LLM provider using OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from core.llm.providers.base import BaseLLMProvider
from core.observability.logging import get_logger

log = get_logger("embedding_provider")

# Default extra_body for aiping.cn API
DEFAULT_AIPING_EMBEDDING_EXTRA_BODY: dict[str, Any] = {
    "provider": {
        "only": [],
        "order": [],
        "sort": "latency",
        "input_price_range": [0, 0],
        "output_price_range": [0, 0],
        "input_length_range": [],
        "output_length_range": [],
        "throughput_range": [],
        "latency_range": [],
    },
    "consume_type": "api",
}


class EmbeddingProvider(BaseLLMProvider):
    """OpenAI-compatible embedding provider using the official openai library."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-3-large",
        timeout: float = 30.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._model = model
        self._is_ollama = "ollama" in base_url.lower() or "11434" in base_url
        self._extra_body = extra_body
        self._is_aiping = "aiping" in base_url.lower()

        # Normalize base URL
        if self._is_ollama:
            # For Ollama, remove /v1 suffix if present
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            self._ollama_base_url = base_url
        else:
            # For OpenAI-compatible APIs, ensure /v1 suffix
            if not base_url.endswith("/v1"):
                base_url = base_url.rstrip("/") + "/v1"
            self._ollama_base_url = None

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

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
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of input texts.
            model: Optional model override.

        Returns:
            List of embedding vectors.
        """
        model_name = model or self._model

        if self._is_ollama:
            # Ollama uses /api/embeddings endpoint with different format
            import httpx

            embeddings: list[list[float]] = []
            async with httpx.AsyncClient(timeout=60.0) as client:
                for text in texts:
                    response = await client.post(
                        f"{self._ollama_base_url}/api/embeddings",
                        json={"model": model_name, "prompt": text},
                    )
                    response.raise_for_status()
                    data: dict[str, Any] = response.json()
                    embeddings.append(data["embedding"])
            return embeddings

        # Build kwargs for OpenAI-compatible API
        kwargs: dict[str, Any] = {
            "model": model_name,
            "input": texts,
        }

        # Add extra_body for aiping.cn or custom providers
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        elif self._is_aiping:
            kwargs["extra_body"] = DEFAULT_AIPING_EMBEDDING_EXTRA_BODY

        # Use OpenAI-compatible API via official library
        response = await self._client.embeddings.create(**kwargs)

        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query text.

        Args:
            text: Input text.

        Returns:
            Embedding vector.
        """
        result = await self.embed([text])
        return result[0] if result else []

    async def close(self) -> None:
        """Clean up resources."""
        await self._client.close()
