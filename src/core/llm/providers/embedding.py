"""Embedding LLM provider using LangChain's OpenAIEmbeddings."""

from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings

from core.llm.providers.base import BaseLLMProvider
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
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of input texts.
            model: Optional model override (not supported by LangChain).

        Returns:
            List of embedding vectors.
        """
        import httpx

        if self._is_ollama and self._ollama_endpoint:
            # Use Ollama's native /api/embeddings endpoint
            embeddings = []
            async with httpx.AsyncClient(timeout=60.0) as client:
                for text in texts:
                    response = await client.post(
                        self._ollama_endpoint,
                        json={"model": model or self._model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings.append(data["embedding"])
            return embeddings

        return await self._client.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query text.

        Args:
            text: Input text.

        Returns:
            Embedding vector.
        """
        return await self._client.aembed_query(text)

    async def close(self) -> None:
        """Clean up resources."""
        pass
