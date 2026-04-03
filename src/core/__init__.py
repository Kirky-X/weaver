# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core module - Foundation components for the weaver application.

This module provides the core infrastructure including:
- db: Database connection pools (PostgreSQL, Neo4j)
- cache: Redis caching layer
- event: Event bus for domain events
- health: Pre-startup health checking
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

from core.cache import RedisClient
from core.db import (
    Article,
    ArticleVector,
    Base,
    CategoryType,
    EmotionType,
    EntityVector,
    Neo4jPool,
    PersistStatus,
    PostgresPool,
    SourceAuthority,
    VectorType,
)
from core.event import BaseEvent, EventBus, FallbackEvent
from core.health import PreStartupHealthChecker, ServiceCheckResult, run_pre_startup_health_check
from core.llm import CallPoint, LLMTask, LLMType
from core.observability import MetricsCollector, configure_tracing, get_logger, get_tracer
from core.prompt import PromptLoader
from core.resilience import CircuitBreaker
from core.utils import get_current_time_with_timezone

__all__ = [
    "Article",
    "ArticleVector",
    "Base",
    "BaseEvent",
    "CallPoint",
    "CategoryType",
    "CircuitBreaker",
    "EmotionType",
    "EntityVector",
    "EventBus",
    "FallbackEvent",
    "LLMTask",
    "LLMType",
    "MetricsCollector",
    "Neo4jPool",
    "PersistStatus",
    "PostgresPool",
    "PreStartupHealthChecker",
    "PromptLoader",
    "RedisClient",
    "ServiceCheckResult",
    "SourceAuthority",
    "VectorType",
    "configure_tracing",
    "get_current_time_with_timezone",
    "get_logger",
    "get_tracer",
    "run_pre_startup_health_check",
]
