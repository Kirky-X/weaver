# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified LLM client with label-based provider selection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel

from core.constants import RedisKeys
from core.llm.label import Label
from core.llm.output_validator import parse_llm_json
from core.llm.pool_manager import PoolManagerConfig, ProviderPoolManager
from core.llm.registry import ProviderInstanceConfig, ProviderRegistry
from core.llm.request import LLMRequest
from core.llm.router import LabelRouter
from core.llm.token_budget import TokenBudgetManager
from core.llm.types import CallPoint, LLMType
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from core.utils.time_utils import get_current_time_with_timezone

log = get_logger("llm_client")

# Type variable for generic output model
T = TypeVar("T", bound=BaseModel)

# Embedding cache settings
EMBEDDING_CACHE_PREFIX = RedisKeys.EMBEDDING_PREFIX
EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days


class LLMClient:
    """Unified entry point for all LLM interactions with label-based routing.

    This is the primary interface for making LLM calls. It supports:
    - Label-based provider selection (e.g., "chat.aiping.GLM-4-9B-0414")
    - Automatic fallback chains
    - Structured output parsing
    - Embedding operations with caching
    - Rerank operations

    Usage:
        client = LLMClient(pool_manager, prompt_loader)

        # Chat call with label
        response = await client.call(
            "chat.cc_stitch.claude-sonnet-4",
            payload={"user_content": "Hello"},
        )

        # Embedding
        vectors = await client.embed(
            "embedding.embedding.qwen3-embedding:0.6b",
            texts=["text1", "text2"],
        )

        # Rerank
        results = await client.rerank(
            "rerank.jina.jina-reranker-v2",
            query="search query",
            documents=["doc1", "doc2"],
        )
    """

    def __init__(
        self,
        pool_manager: ProviderPoolManager,
        prompt_loader: PromptLoader,
        router: LabelRouter | None = None,
        token_budget: TokenBudgetManager | None = None,
        redis_client: Any = None,
    ) -> None:
        """Initialize LLM client.

        Args:
            pool_manager: Provider pool manager.
            prompt_loader: TOML prompt loader.
            router: Optional label router (created from pool_manager if not provided).
            token_budget: Token budget manager for truncation.
            redis_client: Optional Redis client for embedding cache.
        """
        self._pool_manager = pool_manager
        self._prompts = prompt_loader
        self._router = router or LabelRouter(pool_manager)
        self._budget = token_budget or TokenBudgetManager()
        self._redis = redis_client

        # Call point configurations (loaded from config)
        self._call_point_configs: dict[str, dict[str, Any]] = {}

    def configure_call_point(
        self,
        call_point: str,
        primary_label: str,
        fallback_labels: list[str] | None = None,
    ) -> None:
        """Configure routing for a call point.

        Args:
            call_point: Call point name.
            primary_label: Primary label string.
            fallback_labels: Optional fallback label strings.
        """
        self._call_point_configs[call_point] = {
            "primary": primary_label,
            "fallbacks": fallback_labels or [],
        }
        self._router.configure_call_point(call_point, primary_label, fallback_labels)

    # -------------------------------------------------------------------------
    # Core Methods
    # -------------------------------------------------------------------------

    async def call(
        self,
        label: str | Label,
        payload: dict[str, Any],
        fallback_labels: list[str | Label] | None = None,
        output_model: type[T] | None = None,
        priority: int = 5,
        timeout: float | None = None,
    ) -> T | str:
        """Make an LLM call with label-based routing.

        Args:
            label: Label string or Label object (e.g., "chat.aiping.GLM-4-9B-0414").
            payload: Request payload containing prompt data.
            fallback_labels: Optional list of fallback labels.
            output_model: Optional Pydantic model for structured output.
            priority: Request priority (lower = higher priority).
            timeout: Optional timeout override.

        Returns:
            Parsed output model if output_model provided, otherwise raw string.

        Raises:
            AllProvidersFailedError: If all providers in the chain fail.
            InvalidLabelError: If label format is invalid.
        """
        # Parse label if string
        parsed_label = label if isinstance(label, Label) else Label.parse(label)

        # Parse fallback labels
        parsed_fallbacks: list[Label] | None = None
        if fallback_labels:
            parsed_fallbacks = [
                fb if isinstance(fb, Label) else Label.parse(fb) for fb in fallback_labels
            ]

        # Build request
        request = LLMRequest(
            label=parsed_label,
            payload=payload,
            priority=priority,
            timeout=timeout,
            fallback_labels=parsed_fallbacks or [],
        )

        # Execute
        response = await self._pool_manager.execute(request, parsed_fallbacks)

        log.debug(
            "llm_call_complete",
            label=str(parsed_label),
            latency_ms=response.latency_ms,
            attempt=response.attempt,
        )

        # Parse output if model provided
        if output_model:
            return parse_llm_json(response.content, output_model)

        return response.content

    async def call_at(
        self,
        call_point: CallPoint | str,
        payload: dict[str, Any],
        output_model: type[T] | None = None,
        priority: int = 5,
    ) -> T | str:
        """Make an LLM call using call point configuration.

        This method uses pre-configured routing for call points.

        Args:
            call_point: Call point enum or name.
            payload: Request payload.
            output_model: Optional Pydantic model for structured output.
            priority: Request priority.

        Returns:
            Parsed output model or raw string.
        """
        cp_name = call_point.value if isinstance(call_point, CallPoint) else call_point

        # Get call point config
        config = self._call_point_configs.get(cp_name)
        if not config:
            raise ValueError(f"Call point not configured: {cp_name}")

        # Get label and fallbacks
        primary_label = Label.parse(config["primary"])
        fallback_labels = [Label.parse(fb) for fb in config.get("fallbacks", [])]

        # Build system prompt
        system_prompt = self._prompts.get(cp_name)
        current_time = get_current_time_with_timezone()
        system_prompt = f"当前时间: {current_time}\n\n{system_prompt}"

        # Build user content
        user_content = json.dumps(payload, ensure_ascii=False, default=str)

        # Handle retry hint
        if "_retry_hint" in payload:
            system_prompt += f"\n\n{payload.pop('_retry_hint')}"

        # Build request payload
        request_payload = {
            "system_prompt": system_prompt,
            "user_content": user_content,
            **payload,
        }

        return await self.call(
            label=primary_label,
            payload=request_payload,
            fallback_labels=fallback_labels,
            output_model=output_model,
            priority=priority,
        )

    async def embed(
        self,
        label: str | Label,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Generate embeddings for texts.

        Args:
            label: Embedding label (e.g., "embedding.aiping.Qwen3-Embedding-0.6B").
            texts: List of texts to embed.
            batch_size: Batch size for API calls.

        Returns:
            List of embedding vectors.
        """
        parsed_label = label if isinstance(label, Label) else Label.parse(label)

        # Ensure it's an embedding label
        if parsed_label.llm_type != LLMType.EMBEDDING:
            raise ValueError(f"Label must be embedding type, got: {parsed_label.llm_type}")

        all_embeddings: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache
        if self._redis:
            for i, text in enumerate(texts):
                cache_key = self._make_cache_key(text)
                try:
                    cached = await self._redis.get(cache_key)
                    if cached:
                        all_embeddings[i] = json.loads(cached)
                        continue
                except Exception as exc:
                    log.debug("embedding_cache_read_failed", error=str(exc))

                uncached_indices.append(i)
                uncached_texts.append(text)
        else:
            uncached_indices = list(range(len(texts)))
            uncached_texts = texts

        # Compute embeddings for uncached texts
        if uncached_texts:
            new_embeddings: list[list[float]] = []

            for i in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[i : i + batch_size]

                request = LLMRequest(
                    label=parsed_label,
                    payload={"texts": batch},
                    priority=5,
                )

                response = await self._pool_manager.execute(request)
                batch_embeddings = response.content
                new_embeddings.extend(batch_embeddings)

            # Store in cache and result
            for idx, embedding in zip(uncached_indices, new_embeddings):
                all_embeddings[idx] = embedding

                if self._redis and embedding:
                    cache_key = self._make_cache_key(texts[idx])
                    try:
                        await self._redis.setex(
                            cache_key,
                            EMBEDDING_CACHE_TTL,
                            json.dumps(embedding),
                        )
                    except Exception as exc:
                        log.debug("embedding_cache_write_failed", error=str(exc))

        log.debug(
            "embed_complete",
            label=str(parsed_label),
            total=len(texts),
            cached=len(texts) - len(uncached_texts),
            computed=len(uncached_texts),
        )

        return [e or [0.0] * 1024 for e in all_embeddings]

    async def rerank(
        self,
        label: str | Label,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rerank documents based on relevance to query.

        Args:
            label: Rerank label (e.g., "rerank.jina.jina-reranker-v2").
            query: Search query.
            documents: List of documents to rerank.
            top_n: Number of results to return (default: all).

        Returns:
            List of results with "index" and "score" keys.
        """
        parsed_label = label if isinstance(label, Label) else Label.parse(label)

        # Ensure it's a rerank label
        if parsed_label.llm_type != LLMType.RERANK:
            raise ValueError(f"Label must be rerank type, got: {parsed_label.llm_type}")

        request = LLMRequest(
            label=parsed_label,
            payload={
                "query": query,
                "documents": documents,
                "top_n": top_n or len(documents),
            },
            priority=5,
        )

        response = await self._pool_manager.execute(request)

        log.debug(
            "rerank_complete",
            label=str(parsed_label),
            num_documents=len(documents),
            latency_ms=response.latency_ms,
        )

        return response.content

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

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

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """Get metrics for all providers.

        Returns:
            Dictionary of provider metrics.
        """
        return self._pool_manager.get_all_metrics()

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    async def create_from_config(
        cls,
        config_path: str,
        prompt_loader: PromptLoader,
        redis_client: Any = None,
    ) -> LLMClient:
        """Create LLMClient from configuration file.

        Args:
            config_path: Path to llm.toml configuration file.
            prompt_loader: Prompt loader instance.
            redis_client: Optional Redis client.

        Returns:
            Configured LLMClient instance.
        """
        import tomllib
        from pathlib import Path

        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_file, "rb") as f:
            config = tomllib.load(f)

        # Create registry and pool manager
        registry = ProviderRegistry.get_instance()

        # Get pool manager config
        global_config = config.get("global", {})
        pool_config = PoolManagerConfig(
            circuit_breaker_threshold=global_config.get("circuit_breaker_threshold", 5),
            circuit_breaker_timeout=global_config.get("circuit_breaker_timeout", 60.0),
            default_timeout=global_config.get("default_timeout", 120.0),
        )

        # Create rate limiter if Redis is available
        rate_limiter = None
        if redis_client:
            from core.llm.rate_limiter import RedisTokenBucket

            rate_limiter = RedisTokenBucket(redis_client)

        pool_manager = ProviderPoolManager(
            registry=registry,
            rate_limiter=rate_limiter,
            config=pool_config,
        )

        # Register providers
        providers_config = config.get("providers", {})
        for name, provider_cfg in providers_config.items():
            import os

            # Resolve environment variables in API key
            api_key = provider_cfg.get("api_key", "")
            if api_key.startswith("${") and api_key.endswith("}"):
                env_var = api_key[2:-1]
                api_key = os.environ.get(env_var, "")

            # Parse capabilities
            from core.llm.registry import ProviderCapability

            capabilities_str = provider_cfg.get("capabilities", ["chat"])
            if isinstance(capabilities_str, list):
                capabilities = frozenset(ProviderCapability(c.strip()) for c in capabilities_str)
            else:
                capabilities = frozenset({ProviderCapability.CHAT})

            instance_config = ProviderInstanceConfig(
                name=name,
                provider_type=provider_cfg.get("type", "openai"),
                model=provider_cfg.get("model", ""),
                api_key=api_key,
                base_url=provider_cfg.get("base_url", ""),
                rpm_limit=provider_cfg.get("rpm_limit", 60),
                concurrency=provider_cfg.get("concurrency", 5),
                timeout=provider_cfg.get("timeout", 120.0),
                priority=provider_cfg.get("priority", 100),
                weight=provider_cfg.get("weight", 100),
                capabilities=capabilities,
                extra_body=provider_cfg.get("extra_body"),
            )

            await pool_manager.register_provider(instance_config)

        # Start all pools
        await pool_manager.start_all()

        # Set default providers
        default_chat = global_config.get("default_chat_provider")
        if default_chat:
            pool_manager.set_default_provider(LLMType.CHAT, default_chat)

        default_embedding = global_config.get("default_embedding_provider")
        if default_embedding:
            pool_manager.set_default_provider(LLMType.EMBEDDING, default_embedding)

        # Create router and client
        router = LabelRouter(pool_manager)

        client = cls(
            pool_manager=pool_manager,
            prompt_loader=prompt_loader,
            router=router,
            redis_client=redis_client,
        )

        # Configure call points
        call_points = config.get("call-points", {})
        for cp_name, cp_cfg in call_points.items():
            primary = cp_cfg.get("primary", "")
            fallbacks = cp_cfg.get("fallbacks", [])
            if primary:
                client.configure_call_point(cp_name, primary, fallbacks)

        return client

    async def close(self) -> None:
        """Close the client and release resources."""
        await self._pool_manager.close_all()
