# Copyright (c) 2026 KirkyX. All Rights Reserved
"""aiping Rerank provider using custom REST API.

This module implements a Rerank provider for the aiping AI service,
which uses a custom REST API format with Bearer token authentication.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.llm.providers.base import BaseLLMProvider
from core.llm.request import LLMCallResult, TokenUsage
from core.observability.logging import get_logger

log = get_logger("aiping_rerank_provider")


class AIPingRerankProvider(BaseLLMProvider):
    """Rerank provider for aiping AI service.

    aiping provides a custom REST API for reranking with Bearer token authentication.
    The API endpoint is /rerank and expects a specific request/response format.

    API Reference:
        POST /rerank
        Headers: Authorization: Bearer {api_key}
        Body: {
            "model": str,
            "query": str,
            "documents": list[str],
            "top_n": int (optional),
            "return_documents": bool (optional),
            "extra_body": dict (optional)
        }
        Response: {
            "results": [
                {"index": int, "relevance_score": float, "document": str}
            ]
        }
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "Qwen3-Reranker-0.6B",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def chat(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Not implemented for rerank provider."""
        raise NotImplementedError("Use ChatProvider for chat completions")

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Not implemented for rerank provider."""
        raise NotImplementedError("Use EmbeddingProvider for embeddings")

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> LLMCallResult:
        """Rerank documents by relevance to a query using aiping API.

        Args:
            query: The query to rank against.
            documents: List of document texts.
            top_n: Number of top results to return.

        Returns:
            LLMCallResult with rerank results and token usage.

        Raises:
            httpx.HTTPStatusError: On API errors.
            httpx.TimeoutException: On timeout.
        """
        if not documents:
            return LLMCallResult(content=[], token_usage=TokenUsage())

        request_body: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/rerank",
                json=request_body,
                headers=headers,
            )
            response.raise_for_status()

            result: dict[str, Any] = response.json()
            api_results = result.get("results", [])

            results: list[dict[str, Any]] = [
                {
                    "index": item.get("index", i),
                    "score": item.get("relevance_score", 0.0),
                }
                for i, item in enumerate(api_results)
                if i < top_n
            ]

            # 尝试从 API 响应中提取 token 用量
            usage_data = result.get("usage", {})
            token_usage = TokenUsage(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
            )

            # 如果 API 未返回 token 用量,进行估算
            if token_usage.input_tokens == 0:
                total_chars = len(query) + sum(len(d) for d in documents)
                token_usage.input_tokens = int(total_chars / 4)

            return LLMCallResult(
                content=results,
                token_usage=token_usage,
            )

    async def close(self) -> None:
        """Clean up resources.

        No explicit cleanup needed for this provider.
        """
        pass
