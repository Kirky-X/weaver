# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Provider pool for managing a single LLM provider's resources."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.llm.registry import ProviderInstanceConfig
from core.llm.request import LLMRequest, LLMResponse, ProviderMetrics
from core.observability.logging import get_logger
from core.resilience.circuit_breaker import CBState, CircuitBreaker

if TYPE_CHECKING:
    from core.llm.providers.base import BaseLLMProvider
    from core.llm.rate_limiter import RedisTokenBucket

log = get_logger("provider_pool")


class HealthStatus(str, Enum):
    """健康状态。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class PoolTask:
    """池任务封装。"""

    request: LLMRequest
    future: asyncio.Future[LLMResponse]
    attempt: int = 0

    def __lt__(self, other: PoolTask) -> bool:
        """支持 PriorityQueue 排序。"""
        return self.request.priority < other.request.priority


class ProviderPool:
    """单个供应商的资源池。

    管理：
    - 优先级任务队列
    - 并发控制信号量
    - 速率限制
    - 熔断器
    - 健康指标
    """

    def __init__(
        self,
        config: ProviderInstanceConfig,
        provider: BaseLLMProvider,
        rate_limiter: RedisTokenBucket | None = None,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
    ) -> None:
        """初始化供应商池。

        Args:
            config: 供应商实例配置
            provider: LLM 供应商实例
            rate_limiter: 可选的 Redis 令牌桶限流器
            circuit_breaker_threshold: 熔断器失败阈值
            circuit_breaker_timeout: 熔断器冷却时间
        """
        self.config = config
        self._provider = provider
        self._rate_limiter = rate_limiter

        # 资源管理
        self._queue: asyncio.PriorityQueue[tuple[int, int, PoolTask]] = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._circuit_breaker = CircuitBreaker(
            threshold=circuit_breaker_threshold,
            timeout_secs=circuit_breaker_timeout,
            provider=config.name,
        )

        # 指标
        self._metrics = ProviderMetrics()
        self._active_requests = 0
        self._lock = asyncio.Lock()

        # Worker 管理
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    @property
    def name(self) -> str:
        """池名称。"""
        return self.config.name

    @property
    def is_available(self) -> bool:
        """检查供应商是否可用。"""
        return (
            self._circuit_breaker.state != CBState.OPEN
            and self._active_requests < self.config.concurrency
        )

    @property
    def health_status(self) -> HealthStatus:
        """获取健康状态。"""
        if self._circuit_breaker.state == CBState.OPEN:
            return HealthStatus.UNHEALTHY

        if self._metrics.success_rate < 0.5:
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    async def submit(self, request: LLMRequest) -> LLMResponse:
        """提交请求到池。

        Args:
            request: LLM 请求

        Returns:
            LLM 响应
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[LLMResponse] = loop.create_future()
        task = PoolTask(request=request, future=future)

        await self._queue.put((request.priority, id(task), task))
        return await future

    async def start(self, worker_count: int | None = None) -> None:
        """启动 Worker 协程。

        Args:
            worker_count: Worker 数量，默认使用配置的并发数
        """
        if self._running:
            return

        self._running = True
        count = worker_count or self.config.concurrency

        for _ in range(count):
            worker = asyncio.create_task(self._worker_loop())
            self._workers.append(worker)

        log.info("provider_pool_started", pool=self.name, workers=count)

    async def stop(self) -> None:
        """停止所有 Worker。"""
        self._running = False

        for worker in self._workers:
            worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        log.info("provider_pool_stopped", pool=self.name)

    async def _worker_loop(self) -> None:
        """Worker 协程主循环。"""
        while self._running:
            try:
                # 从队列获取任务
                _, _, task = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )

                async with self._semaphore:
                    try:
                        response = await self._execute_task(task)
                        if not task.future.done():
                            task.future.set_result(response)
                    except Exception as exc:
                        if not task.future.done():
                            task.future.set_exception(exc)

                self._queue.task_done()

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error(
                    "worker_unexpected_error",
                    pool=self.name,
                    error=str(exc),
                )

    async def _execute_task(self, task: PoolTask) -> LLMResponse:
        """执行单个任务。"""
        request = task.request
        label = request.label

        # 1. 熔断器检查
        if await self._circuit_breaker.is_open():
            raise CircuitOpenError(f"Circuit breaker is OPEN for provider {self.name}")

        # 2. 速率限制
        if self._rate_limiter and self.config.rpm_limit > 0:
            wait_time = await self._rate_limiter.consume(
                self.name,
                self.config.rpm_limit,
            )
            if wait_time > 0:
                await asyncio.sleep(wait_time)

        # 3. 执行调用
        start_time = time.monotonic()
        self._active_requests += 1

        try:
            content = await self._dispatch_to_provider(request)
            latency_ms = (time.monotonic() - start_time) * 1000

            # 记录成功
            await self._record_success(latency_ms)

            return LLMResponse(
                content=content,
                label=label,
                latency_ms=latency_ms,
                attempt=task.attempt,
            )

        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000

            # 记录失败
            await self._record_failure(str(exc))

            raise

        finally:
            self._active_requests -= 1

    async def _dispatch_to_provider(self, request: LLMRequest) -> Any:
        """分发请求到供应商。"""
        label = request.label
        payload = request.payload

        # 根据 LLM 类型分发
        if label.llm_type.value == "chat":
            return await self._provider.chat(
                system_prompt=payload.get("system_prompt", ""),
                user_content=payload.get("user_content", ""),
                model=label.model,
                temperature=payload.get("temperature", 0.0),
                max_tokens=payload.get("max_tokens"),
            )
        elif label.llm_type.value == "embedding":
            texts = payload.get("texts", [])
            if not texts:
                raise ValueError("Embedding request must contain 'texts' in payload")
            return await self._provider.embed(
                texts=texts,
                model=label.model,
            )
        elif label.llm_type.value == "rerank":
            # Rerank 特殊处理
            query = payload.get("query", "")
            documents = payload.get("documents", [])
            top_n = payload.get("top_n", len(documents))

            if hasattr(self._provider, "rerank"):
                rerank_func = self._provider.rerank
                return await rerank_func(
                    query=query,
                    documents=documents,
                    top_n=top_n,
                )
            raise NotImplementedError(f"Provider {self.name} does not support rerank")

        raise ValueError(f"Unknown LLM type: {label.llm_type}")

    async def _record_success(self, latency_ms: float) -> None:
        """记录成功调用。"""
        async with self._lock:
            self._metrics.record_success(latency_ms)

        await self._circuit_breaker.record_success()

    async def _record_failure(self, error: str) -> None:
        """记录失败调用。"""
        async with self._lock:
            self._metrics.record_failure(error)

        await self._circuit_breaker.record_failure()

    def get_metrics(self) -> ProviderMetrics:
        """获取指标快照。"""
        return ProviderMetrics(
            total_requests=self._metrics.total_requests,
            successful_requests=self._metrics.successful_requests,
            failed_requests=self._metrics.failed_requests,
            total_latency_ms=self._metrics.total_latency_ms,
            last_request_time=self._metrics.last_request_time,
            last_error=self._metrics.last_error,
            last_error_time=self._metrics.last_error_time,
        )

    async def close(self) -> None:
        """关闭供应商池并释放资源。"""
        await self.stop()
        await self._provider.close()


class CircuitOpenError(Exception):
    """熔断器开启异常。"""

    pass
