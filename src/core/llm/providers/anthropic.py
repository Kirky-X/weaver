# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Anthropic Claude API provider using LangChain's ChatAnthropic."""

from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm.providers.base import BaseLLMProvider
from core.llm.request import LLMCallResult, TokenUsage
from core.observability.logging import get_logger

log = get_logger("anthropic_provider")


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API provider using LangChain.

    Supports the Anthropic Messages API format via langchain-anthropic.

    Args:
        api_key: Anthropic API key (or dummy key for proxy).
        base_url: Base URL for the API (e.g., http://127.0.0.1:5000).
        model: Model name (e.g., claude-sonnet-4-20250514).
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "claude-sonnet-4-20250514",
        timeout: float = 300.0,
    ) -> None:
        self._default_model = model
        self._base_url = base_url
        self._client = ChatAnthropic(
            api_key=api_key,
            anthropic_api_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=0,
        )

    async def chat(
        self,
        system_prompt: str,
        user_content: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMCallResult:
        """Send a chat completion request to Anthropic API.

        Args:
            system_prompt: System message content.
            user_content: User message content.
            model: Optional model override.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in response.

        Returns:
            LLMCallResult containing response text and token usage.
        """
        client = self._client
        if model and model != self._default_model:
            client = client.bind(model=model)

        kwargs: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        log.debug(
            "anthropic_request",
            model=model or self._default_model,
            max_tokens=max_tokens,
        )

        response = await client.ainvoke(messages, **kwargs)

        content = response.content
        result = ""

        # Handle list of content blocks (Claude extended thinking format)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # Extract text from text blocks, skip thinking blocks
                    if block.get("type") == "text":
                        result += block.get("text", "")
                elif hasattr(block, "text"):
                    result += block.text
                elif isinstance(block, str):
                    result += block
        else:
            result = str(content)

        # Extract token usage from response_metadata
        usage = response.response_metadata.get("usage", {})
        token_usage = TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

        log.debug(
            "anthropic_response",
            response_length=len(result),
            input_tokens=token_usage.input_tokens,
            output_tokens=token_usage.output_tokens,
        )

        return LLMCallResult(content=result, token_usage=token_usage)

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Not implemented for Anthropic provider.

        Raises:
            NotImplementedError: Anthropic provider does not support embeddings.
        """
        raise NotImplementedError("Use EmbeddingProvider for embeddings")

    async def close(self) -> None:
        """Clean up resources.

        No explicit cleanup needed for ChatAnthropic client.
        """
        pass
