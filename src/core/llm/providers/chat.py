# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Chat LLM provider using LangChain's ChatOpenAI."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.llm.providers.base import BaseLLMProvider
from core.llm.request import LLMCallResult, TokenUsage
from core.observability.logging import get_logger

log = get_logger("chat_provider")

# Default timeout for LLM calls (seconds)
DEFAULT_TIMEOUT = 120.0


class ChatProvider(BaseLLMProvider):
    """OpenAI-compatible chat provider using LangChain."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "gpt-4o",
        timeout: float = 30.0,
    ) -> None:
        self._default_model = model
        self._base_url = base_url
        self._timeout = timeout
        self._client = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            request_timeout=timeout,
            max_retries=0,  # We handle retries in the queue manager
        )

    async def chat(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMCallResult:
        """Send a chat completion request.

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
        client = self._client
        if model and model != self._default_model:
            client = client.bind(model=model)

        # For Ollama models, use extra_body to pass Ollama-specific parameters
        # This disables thinking mode to ensure JSON output
        extra_kwargs: dict[str, Any] = {}
        model_name = model or self._default_model
        if "ollama" in self._base_url.lower() or "qwen" in model_name.lower():
            extra_kwargs["extra_body"] = {"think": False}

        kwargs: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        # Apply timeout protection to prevent indefinite hanging
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.ainvoke(messages, **kwargs)

                # Extract token usage from response metadata
                token_usage_data = response.response_metadata.get("token_usage", {})
                token_usage = TokenUsage(
                    input_tokens=token_usage_data.get("prompt_tokens", 0),
                    output_tokens=token_usage_data.get("completion_tokens", 0),
                    total_tokens=token_usage_data.get("total_tokens", 0),
                )

                return LLMCallResult(content=response.content, token_usage=token_usage)
        except TimeoutError:
            log.error(
                "llm_chat_timeout",
                timeout=self._timeout,
                model=model_name,
                base_url=self._base_url,
            )
            raise TimeoutError(
                f"LLM request timed out after {self._timeout} seconds. "
                f"Model: {model_name}, Base URL: {self._base_url}"
            )

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
        """Clean up resources.

        No explicit cleanup needed for ChatOpenAI client.
        """
