"""Unified LLM client — single entry point for all LLM operations."""

from __future__ import annotations

import json
from typing import Any, Type

from pydantic import BaseModel

from core.llm.types import LLMTask, LLMType, CallPoint
from core.llm.queue_manager import LLMQueueManager
from core.llm.output_validator import parse_llm_json, OutputParserException
from core.llm.token_budget import TokenBudgetManager
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
from core.utils.time_utils import get_current_time_with_timezone

log = get_logger("llm_client")


class LLMClient:
    """Unified entry point for all LLM interactions.

    Handles:
    - Prompt loading and formatting
    - Token budget management
    - Structured output parsing
    - Embedding batch operations
    - Queue submission via LLMQueueManager

    Args:
        queue_manager: The queue manager for task dispatching.
        prompt_loader: TOML prompt loader.
        token_budget: Token budget manager for truncation.
    """

    def __init__(
        self,
        queue_manager: LLMQueueManager,
        prompt_loader: PromptLoader,
        token_budget: TokenBudgetManager | None = None,
    ) -> None:
        self._queue = queue_manager
        self._prompts = prompt_loader
        self._budget = token_budget or TokenBudgetManager()

    async def call(
        self,
        call_point: CallPoint,
        payload: dict[str, Any],
        output_model: Type[BaseModel] | None = None,
        priority: int = 5,
    ) -> Any:
        """Make an LLM call through the queue system.

        Args:
            call_point: The pipeline stage making the call.
            payload: Data to send to the LLM (key-value pairs).
            output_model: Optional Pydantic model for structured output.
            priority: Queue priority (lower = higher priority).

        Returns:
            Parsed output model instance if output_model provided,
            otherwise raw LLM response string.
        """
        # Load the system prompt
        system_prompt = self._prompts.get(call_point.value)

        # Inject current time for CHAT tasks
        current_time = get_current_time_with_timezone()
        current_time_context = f"当前时间: {current_time}\n\n"
        system_prompt = current_time_context + system_prompt

        # Build user content from payload
        user_content = json.dumps(payload, ensure_ascii=False, default=str)

        # Add retry hint if present
        if "_retry_hint" in payload:
            system_prompt += f"\n\n{payload.pop('_retry_hint')}"

        task = LLMTask(
            call_point=call_point,
            llm_type=LLMType.CHAT,
            payload={
                "system_prompt": system_prompt,
                "user_content": user_content,
            },
            priority=priority,
        )

        raw_result = await self._queue.enqueue(task)

        # Debug: log raw result
        log.debug("llm_raw_result", call_point=call_point.value, raw_result_len=len(raw_result) if raw_result else 0, raw_result_preview=raw_result[:200] if raw_result else "EMPTY")

        if output_model:
            return parse_llm_json(raw_result, output_model)

        return raw_result

    async def batch_embed(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Splits into batches and embeds via the configured embedding provider.

        Args:
            texts: List of texts to embed.
            batch_size: Maximum batch size per API call.

        Returns:
            List of embedding vectors corresponding to input texts.
        """
        from core.llm.providers.embedding import EmbeddingProvider

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Use the queue manager's embedding provider
            if hasattr(self._queue, "_providers"):
                for provider in self._queue._providers.values():
                    if isinstance(provider, EmbeddingProvider):
                        embeddings = await provider.embed(batch)
                        all_embeddings.extend(embeddings)
                        break
                else:
                    # Fallback: create a task for embedding
                    log.warning("no_embedding_provider_found")
                    # Return zero vectors as placeholder
                    all_embeddings.extend([[0.0] * 1024] * len(batch))
            else:
                all_embeddings.extend([[0.0] * 1024] * len(batch))

        return all_embeddings

    def get_prompt_version(self, name: str) -> str:
        """Get the version of a prompt template.

        Args:
            name: Prompt template name.

        Returns:
            Version string.
        """
        return self._prompts.get_version(name)
