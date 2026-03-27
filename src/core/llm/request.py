# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified LLM request and response data structures."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.llm.label import Label


@dataclass
class LLMRequest:
    """统一的 LLM 请求结构。

    Attributes:
        label: 调用标签 (type.provider.model)
        payload: 请求数据
        priority: 优先级 (越小越高)
        timeout: 超时时间覆盖
        fallback_labels: 备用标签列表
        metadata: 附加元数据
    """

    label: Label
    payload: dict[str, Any]
    priority: int = 5
    timeout: float | None = None
    fallback_labels: list[Label] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: LLMRequest) -> bool:
        """支持 PriorityQueue 排序。"""
        return self.priority < other.priority


@dataclass
class LLMResponse:
    """统一的 LLM 响应结构。

    Attributes:
        content: 响应内容
        label: 实际使用的标签
        latency_ms: 响应延迟（毫秒）
        tokens_used: Token 使用量
        from_cache: 是否来自缓存
        attempt: 尝试次数
        error: 错误信息（如有）
        metadata: 附加元数据
    """

    content: Any
    label: Label
    latency_ms: float
    tokens_used: int | None = None
    from_cache: bool = False
    attempt: int = 0
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """请求是否成功。"""
        return self.error is None


@dataclass
class EmbeddingRequest:
    """Embedding 请求结构。

    Attributes:
        label: 调用标签
        texts: 待嵌入的文本列表
        batch_size: 批处理大小
        metadata: 附加元数据
    """

    label: Label
    texts: list[str]
    batch_size: int = 32
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingResponse:
    """Embedding 响应结构。

    Attributes:
        embeddings: 嵌入向量列表
        label: 实际使用的标签
        latency_ms: 响应延迟（毫秒）
        from_cache: 各文本是否来自缓存
        metadata: 附加元数据
    """

    embeddings: list[list[float]]
    label: Label
    latency_ms: float
    from_cache: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankRequest:
    """Rerank 请求结构。

    Attributes:
        label: 调用标签
        query: 查询文本
        documents: 待重排的文档列表
        top_n: 返回的文档数量
        metadata: 附加元数据
    """

    label: Label
    query: str
    documents: list[str]
    top_n: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankResponse:
    """Rerank 响应结构。

    Attributes:
        results: 重排结果列表，每项包含 index 和 score
        label: 实际使用的标签
        latency_ms: 响应延迟（毫秒）
        metadata: 附加元数据
    """

    results: list[dict[str, Any]]  # [{"index": int, "score": float}, ...]
    label: Label
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderMetrics:
    """供应商指标。

    Attributes:
        total_requests: 总请求数
        successful_requests: 成功请求数
        failed_requests: 失败请求数
        total_latency_ms: 总延迟（毫秒）
        last_request_time: 最后请求时间
        last_error: 最后错误信息
        last_error_time: 最后错误时间
    """

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    last_request_time: float | None = None
    last_error: str | None = None
    last_error_time: float | None = None

    @property
    def success_rate(self) -> float:
        """成功率 (0.0 到 1.0)。"""
        total = self.total_requests
        if total == 0:
            return 1.0
        return self.successful_requests / total

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）。"""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    def record_success(self, latency_ms: float) -> None:
        """记录成功调用。

        Args:
            latency_ms: 延迟时间（毫秒）
        """
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency_ms += latency_ms
        self.last_request_time = time.monotonic()

    def record_failure(self, error: str) -> None:
        """记录失败调用。

        Args:
            error: 错误信息
        """
        self.total_requests += 1
        self.failed_requests += 1
        self.last_error = error
        self.last_error_time = time.monotonic()
