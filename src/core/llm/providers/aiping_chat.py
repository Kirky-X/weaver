# Copyright (c) 2026 KirkyX. All Rights Reserved
"""aiping Chat provider with extra_body support for provider routing.

This module implements a Chat provider for the aiping AI service,
which requires special extra_body parameters for provider selection.
"""

from __future__ import annotations

import asyncio
from typing import Any

from openai import AsyncOpenAI

from core.llm.providers.base import BaseLLMProvider
from core.llm.request import LLMCallResult, TokenUsage
from core.observability.logging import get_logger

log = get_logger("aiping_chat_provider")

# Default extra_body for aiping.cn API
DEFAULT_AIPING_EXTRA_BODY: dict[str, Any] = {
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
    }
}


class AIPingChatProvider(BaseLLMProvider):
    """Chat provider for aiping AI service.

    aiping provides OpenAI-compatible API with additional extra_body parameters
    for provider selection and routing optimization.

    API Reference:
        Base URL: https://www.aiping.cn/api/v1
        Models: GLM-4-9B-0414, GLM-Z1-9B-0414, etc.
        Extra Body: Provider routing configuration

    Example:
        provider = AIPingChatProvider(
            api_key="QC-xxx",
            base_url="https://www.aiping.cn/api/v1",
            model="GLM-4-9B-0414",
            extra_body={
                "provider": {
                    "sort": "latency",
                    ...
                }
            }
        )
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "GLM-4-9B-0414",
        timeout: float = 120.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize aiping Chat provider.

        Args:
            api_key: aiping API key (starts with QC-).
            base_url: API base URL (default: https://www.aiping.cn/api/v1).
            model: Model name to use.
            timeout: Request timeout in seconds.
            extra_body: Additional request body parameters for provider routing.
        """
        self._model = model
        self._timeout = timeout
        self._extra_body = extra_body or DEFAULT_AIPING_EXTRA_BODY

        # Ensure base_url ends with /v1
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"

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
    ) -> LLMCallResult:
        """Send a chat completion request to aiping API.

        Args:
            system_prompt: System message content.
            user_content: User message content.
            model: Optional model override.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            LLMCallResult containing response content and token usage.

        Raises:
            TimeoutError: If the request exceeds the timeout threshold.
        """
        model_name = model or self._model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        # Add extra_body for aiping provider routing
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body

        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.chat.completions.create(**kwargs)

                content = response.choices[0].message.content or ""

                # Extract token usage
                usage = response.usage
                token_usage = TokenUsage(
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                )

                return LLMCallResult(content=content, token_usage=token_usage)

        except TimeoutError:
            log.error(
                "aiping_chat_timeout",
                timeout=self._timeout,
                model=model_name,
            )
            raise TimeoutError(
                f"aiping chat request timed out after {self._timeout} seconds. Model: {model_name}"
            )

    async def chat_stream(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ):
        """Stream chat completion from aiping API.

        Args:
            system_prompt: System message content.
            user_content: User message content.
            model: Optional model override.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Yields:
            str: Content chunks from the stream.
        """
        model_name = model or self._model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        # Add extra_body for aiping provider routing
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body

        stream = await self._client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if not chunk.choices:
                continue

            # Handle reasoning_content for thinking models
            delta = chunk.choices[0].delta
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                yield delta.reasoning_content

            if delta.content:
                yield delta.content

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Not implemented for chat provider.

        Raises:
            NotImplementedError: Chat provider does not support embeddings.
        """
        raise NotImplementedError("Use EmbeddingProvider for embeddings")

    async def close(self) -> None:
        """Clean up resources."""
        await self._client.close()
