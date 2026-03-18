# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified LLM client — single entry point for all LLM operations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from core.llm.output_validator import parse_llm_json
from core.llm.queue_manager import LLMQueueManager
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint, LLMTask, LLMType
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from core.utils.time_utils import get_current_time_with_timezone

log = get_logger("llm_client")

EMBEDDING_CACHE_PREFIX = "emb:"
EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60


class LLMClient:
    """Unified entry point for all LLM interactions.

    Handles:
    - Prompt loading and formatting
    - Token budget management
    - Structured output parsing
    - Embedding batch operations with caching
    - Queue submission via LLMQueueManager

    Args:
        queue_manager: The queue manager for task dispatching.
        prompt_loader: TOML prompt loader.
        token_budget: Token budget manager for truncation.
        redis_client: Optional Redis client for embedding cache.
    """

    def __init__(
        self,
        queue_manager: LLMQueueManager,
        prompt_loader: PromptLoader,
        token_budget: TokenBudgetManager | None = None,
        redis_client: Any = None,
    ) -> None:
        self._queue = queue_manager
        self._prompts = prompt_loader
        self._budget = token_budget or TokenBudgetManager()
        self._redis = redis_client

    async def call(
        self,
        call_point: CallPoint,
        payload: dict[str, Any],
        output_model: type[BaseModel] | None = None,
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
        system_prompt = self._prompts.get(call_point.value)

        current_time = get_current_time_with_timezone()
        current_time_context = f"当前时间: {current_time}\n\n"
        system_prompt = current_time_context + system_prompt

        user_content = json.dumps(payload, ensure_ascii=False, default=str)

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

        log.debug(
            "llm_raw_result",
            call_point=call_point.value,
            raw_result_len=len(raw_result) if raw_result else 0,
            raw_result_preview=raw_result[:200] if raw_result else "EMPTY",
        )

        if output_model:
            return parse_llm_json(raw_result, output_model)

        return raw_result

    async def batch_embed(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts with caching.

        Splits into batches and embeds via the configured embedding provider.
        Uses Redis cache to avoid recomputing embeddings for duplicate content.

        Args:
            texts: List of texts to embed.
            batch_size: Maximum batch size per API call.

        Returns:
            List of embedding vectors corresponding to input texts.
        """
        from core.llm.providers.embedding import EmbeddingProvider

        all_embeddings: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        if self._redis:
            for i, text in enumerate(texts):
                cache_key = self._make_cache_key(text)
                try:
                    cached = await self._redis.get(cache_key)
                    if cached:
                        import json as json_mod

                        all_embeddings[i] = json_mod.loads(cached)
                        continue
                except Exception as exc:
                    log.debug("embedding_cache_read_failed", error=str(exc))

                uncached_indices.append(i)
                uncached_texts.append(text)
        else:
            uncached_indices = list(range(len(texts)))
            uncached_texts = texts

        if uncached_texts:
            from core.llm.providers.embedding import EmbeddingProvider

            new_embeddings: list[list[float]] = []
            for i in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[i : i + batch_size]
                if hasattr(self._queue, "_providers"):
                    for provider in self._queue._providers.values():
                        if isinstance(provider, EmbeddingProvider):
                            embeddings = await provider.embed(batch)
                            new_embeddings.extend(embeddings)
                            break
                    else:
                        log.warning("no_embedding_provider_found")
                        new_embeddings.extend([[0.0] * 1024] * len(batch))
                else:
                    new_embeddings.extend([[0.0] * 1024] * len(batch))

            for idx, embedding in zip(uncached_indices, new_embeddings):
                all_embeddings[idx] = embedding

                if self._redis and embedding:
                    cache_key = self._make_cache_key(texts[idx])
                    try:
                        import json as json_mod

                        await self._redis.setex(
                            cache_key,
                            EMBEDDING_CACHE_TTL,
                            json_mod.dumps(embedding),
                        )
                    except Exception as exc:
                        log.debug("embedding_cache_write_failed", error=str(exc))

        log.debug(
            "batch_embed_complete",
            total=len(texts),
            cached=len(texts) - len(uncached_texts),
            computed=len(uncached_texts),
        )

        return [e or [0.0] * 1024 for e in all_embeddings]

    def _make_cache_key(self, text: str) -> str:
        """Generate cache key for embedding.

        Args:
            text: Text content to hash.

        Returns:
            Redis cache key string.
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
        return f"{EMBEDDING_CACHE_PREFIX}{text_hash}"

    def get_prompt_version(self, name: str) -> str:
        """Get the version of a prompt template.

        Args:
            name: Prompt template name.

        Returns:
            Version string.
        """
        return self._prompts.get_version(name)
