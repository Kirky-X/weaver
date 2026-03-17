"""Core module - Foundation components for the weaver application.

This module provides the core infrastructure including:
- db: Database connection pools (PostgreSQL, Neo4j)
- cache: Redis caching layer
- event: Event bus for domain events
- llm: LLM client and providers
- observability: Logging, metrics, and tracing
- prompt: Prompt template management
- resilience: Circuit breaker and retry patterns
- utils: Utility functions

Example usage:
    from core.db import PostgresPool, Neo4jPool
    from core.cache import RedisClient
    from core.observability import get_logger
"""

from core.db import (
    PostgresPool,
    Neo4jPool,
    Base,
    Article,
    ArticleVector,
    EntityVector,
    SourceAuthority,
    ArticleEntity,
    CategoryType,
    PersistStatus,
    EmotionType,
    VectorType,
)
from core.cache import RedisClient, get_redis_client, cache_result, invalidate_cache
from core.event import EventBus, BaseEvent, FallbackEvent
from core.llm import LLMType, CallPoint, LLMTask
from core.observability import get_logger, MetricsCollector, configure_tracing, get_tracer
from core.prompt import PromptLoader
from core.resilience import CircuitBreaker
from core.utils import get_current_time_with_timezone

__all__ = [
    "PostgresPool",
    "Neo4jPool",
    "Base",
    "Article",
    "ArticleVector",
    "EntityVector",
    "SourceAuthority",
    "ArticleEntity",
    "CategoryType",
    "PersistStatus",
    "EmotionType",
    "VectorType",
    "RedisClient",
    "get_redis_client",
    "cache_result",
    "invalidate_cache",
    "EventBus",
    "BaseEvent",
    "FallbackEvent",
    "LLMType",
    "CallPoint",
    "LLMTask",
    "get_logger",
    "MetricsCollector",
    "configure_tracing",
    "get_tracer",
    "PromptLoader",
    "CircuitBreaker",
    "get_current_time_with_timezone",
]
