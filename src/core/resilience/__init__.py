# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core resilience module - Circuit breaker and retry patterns.

公开 API:
- CircuitBreaker: 熔断器
- CBState: 熔断器状态
- DatabaseCircuitBreaker: 数据库专用熔断器 (fail_max=3, reset_timeout=30s)
- retry_db, retry_llm, retry_network: 重试装饰器
"""

from core.llm.utils.json_parser import OutputParserException
from core.resilience.circuit_breaker import CBState, CircuitBreaker
from core.resilience.db_circuit_breaker import DatabaseCircuitBreaker
from core.resilience.retry import (
    retry_db,
    retry_llm,
    retry_network,
    with_db_retry,
    with_llm_retry,
    with_network_retry,
)

__all__ = [
    "CBState",
    "CircuitBreaker",
    "DatabaseCircuitBreaker",
    "OutputParserException",
    "retry_db",
    "retry_llm",
    "retry_network",
    "with_db_retry",
    "with_llm_retry",
    "with_network_retry",
]
