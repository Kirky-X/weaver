# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Base LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.llm.request import LLMCallResult


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
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
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources.

        Subclasses should override this method if they need to release
        resources (e.g., HTTP clients).
        """
        ...
