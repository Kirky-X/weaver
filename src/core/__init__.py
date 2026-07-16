# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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

公开 API:
- PostgresPool: PostgreSQL 连接池
- Neo4jPool: Neo4j 连接池
- RedisClient: Redis 缓存客户端
- EventBus: 事件总线
- PromptLoader: Prompt 模板加载器
- CircuitBreaker: 熔断器
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
from core.event import BaseEvent, EventBus
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
