# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unified LLM client with label-based routing."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any, TypeVar

from cachetools import TTLCache
from pydantic import BaseModel

from core.constants import RedisKeys
from core.llm.cache_key import build_stable_cache_key
from core.llm.prefix_shape import PrefixHashTracker
from core.llm.resilience.pool import AllProvidersFailedError, ProviderPool
from core.llm.routing.router import LabelRouter
from core.llm.types import (
    CACHE_TTL,
    CallPoint,
    GlobalConfig,
    Label,
    LLMType,
    ProviderConfig,
    TokenUsage,
)
from core.llm.utils.json_parser import parse_llm_json
from core.observability import get_logger
from core.observability.metrics import metrics
from core.utils.time_utils import get_current_time_with_timezone

if TYPE_CHECKING:
    from core.event import EventBus
    from core.llm.evaluation.eval_runner import EvalRunner
    from core.llm.routing.smart_router import SmartRouter
    from core.llm.routing.tiered_router import TieredRouter
    from core.prompt.loader import PromptLoader

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Embedding cache settings
EMBEDDING_CACHE_PREFIX = RedisKeys.EMBEDDING_PREFIX
EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days

# Input limits per call point (in characters)
_INPUT_LIMITS: dict[str, int] = {
    "classifier": 600,
    "categorizer": 1100,
    "quality_scorer": 1500,
    "credibility_checker": 2000,
    "analyze": 3000,
    "summary": 2000,
    "entity_extractor": 2000,
    "default": 2000,
}


class LLMClient:
    """统一LLM调用入口.

    提供label路由、fallback、embedding缓存等功能.
    """

    def __init__(
        self,
        providers: list[ProviderConfig],
        global_config: GlobalConfig,
        event_bus: EventBus,
        cache_client: Any = None,
        prompt_loader: PromptLoader | None = None,
        smart_router: SmartRouter | None = None,
        eval_runner: EvalRunner | None = None,
        tiered_router: TieredRouter | None = None,
    ) -> None:
        """初始化LLM客户端.

        Args:
            providers: Provider配置列表
            global_config: 全局配置
            event_bus: 事件总线(必需)
            cache_client: 可选的Redis客户端（用于embedding缓存）
            prompt_loader: 可选的Prompt 加载器（用于call_at方法）
            smart_router: 可选的智能路由器（动态评分选择模型）
            eval_runner: 可选的影子评测器
            tiered_router: 可选的分级路由器（难度分级选择模型）
        """
        self._global_config = global_config
        self._router = LabelRouter(global_config)
        self._smart_router = smart_router
        self._eval_runner = eval_runner
        self._tiered_router = tiered_router
        self._redis = cache_client
        self._prompts = prompt_loader
        self._event_bus = event_bus

        self._response_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1000, ttl=3600)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        # Prefix shape diagnostics tracker (pure observability, does not affect cache logic)
        self._prefix_tracker = PrefixHashTracker()

        # 创建provider池映射,必须传递event_bus
        self._pools: dict[str, ProviderPool] = {}
        for provider_cfg in providers:
            pool = ProviderPool(
                config=provider_cfg,
                event_bus=event_bus,
                circuit_breaker_threshold=global_config.circuit_breaker_threshold,
                circuit_breaker_timeout=global_config.circuit_breaker_timeout,
                global_config=global_config,
            )
            self._pools[provider_cfg.name] = pool

        log.info(
            "llm_client_initialized",
            providers=list(self._pools.keys()),
        )

    @property
    def default_embedding_label(self) -> str:
        """Return the default embedding model label string."""
        return str(self._router.get_default(LLMType.EMBEDDING))

    async def _emit_usage_event(
        self,
        label: Label,
        call_point: CallPoint,
        latency_ms: float,
        token_usage: TokenUsage | None,
        success: bool,
        error_type: str | None = None,
        article_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """发射LLMUsageEvent到EventBus.

        Args:
            label: 调用标签
            call_point: 调用点标识
            latency_ms: 调用延迟
            token_usage: Token使用量
            success: 是否成功
            error_type: 错误类型
            article_id: 关联的文章ID
            task_id: 关联的任务ID
        """
        try:
            from core.event import LLMUsageEvent

            event = LLMUsageEvent(
                label=str(label),
                call_point=call_point.value,
                llm_type=label.llm_type.value,
                provider=label.provider,
                model=label.model,
                tokens=token_usage or TokenUsage(),
                latency_ms=latency_ms,
                success=success,
                error_type=error_type,
                timestamp=get_current_time_with_timezone(),
                article_id=article_id,
                task_id=task_id,
            )
            await self._event_bus.publish(event)
        except Exception as exc:
            log.warning(
                "llm_usage_event_publish_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def call(
        self,
        label: str | Label,
        payload: dict[str, Any],
        call_point: CallPoint | str,
        article_id: str | None = None,
        task_id: str | None = None,
        fallback_labels: list[str | Label] | None = None,
        output_model: type[T] | None = None,
        timeout: float | None = None,
    ) -> T | str:
        """通用LLM调用.

        Args:
            label: 标签或标签字符串
            payload: 调用参数
            call_point: 调用点标识(必需)
            article_id: 文章ID(可选)
            task_id: 任务ID(可选)
            fallback_labels: 备用标签列表
            output_model: 可选的Pydantic模型，用于结构化输出
            timeout: 超时覆盖

        Returns:
            解析后的模型实例或原始字符串
        """
        parsed_label = Label.parse(label) if isinstance(label, str) else label

        if isinstance(call_point, str):
            try:
                cp = CallPoint(call_point)
            except ValueError:
                log.warning(
                    "invalid_call_point",
                    call_point=call_point,
                    fallback="CLASSIFIER",
                )
                cp = CallPoint.CLASSIFIER
        else:
            cp = call_point

        cache_key = self._build_cache_key(cp.value, payload)

        ttl = CACHE_TTL.get(cp.value, CACHE_TTL["default"])

        # Redis cache check (preferred over TTLCache for persistence across restarts)
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    self._cache_hits += 1
                    log.info("llm_cache_hit", label=str(parsed_label), source="redis")
                    if output_model:
                        return parse_llm_json(data["content"], output_model)
                    return data["content"]
            except Exception as exc:
                log.debug("redis_cache_read_failed", error=str(exc))

        # TTLCache handles TTL and eviction automatically
        if cache_key in self._response_cache:
            cached = self._response_cache[cache_key]
            self._cache_hits += 1
            log.info("llm_cache_hit", label=str(parsed_label), source="memory")
            if output_model:
                return parse_llm_json(cached["content"], output_model)
            return cached["content"]

        log.debug("llm_cache_miss", label=str(parsed_label))
        self._cache_misses += 1

        # Truncate input body based on call point limits
        if "body" in payload:
            truncated_payload = dict(payload)
            limit = _INPUT_LIMITS.get(cp.value, _INPUT_LIMITS["default"])
            body = payload["body"]
            title = payload.get("title")
            if title:
                truncated_payload["body"] = f"标题：{title}\n\n正文：{body[:limit]}"
            else:
                truncated_payload["body"] = body[:limit]
        else:
            truncated_payload = payload

        # 构建label链
        labels = self._router.resolve(parsed_label)
        if fallback_labels:
            for fb in fallback_labels:
                fb_label = Label.parse(fb) if isinstance(fb, str) else fb
                if fb_label not in labels:
                    labels.append(fb_label)

        # 按 provider 分组 labels, 执行跨池 fallback
        last_error: Exception | None = None
        for label in labels:
            pool = self._pools.get(label.provider)
            if not pool:
                log.warning(
                    "provider_pool_not_found",
                    provider=label.provider,
                    label=str(label),
                )
                continue

            try:
                response = await pool.execute(
                    labels=[label],  # 每个 pool 只执行自己的 label
                    payload=truncated_payload,
                    call_point=cp.value,
                    timeout=timeout,
                    article_id=article_id,
                    task_id=task_id,
                )

                self._response_cache[cache_key] = {
                    "content": response.content,
                    "token_usage": response.token_usage,
                }

                if self._redis:
                    try:
                        token_usage_dict = {
                            "input_tokens": (
                                response.token_usage.input_tokens if response.token_usage else 0
                            ),
                            "output_tokens": (
                                response.token_usage.output_tokens if response.token_usage else 0
                            ),
                            "total_tokens": (
                                response.token_usage.total_tokens if response.token_usage else 0
                            ),
                        }
                        await self._redis.set(
                            cache_key,
                            json.dumps(
                                {
                                    "content": response.content,
                                    "token_usage": token_usage_dict,
                                },
                                ensure_ascii=False,
                            ),
                            ex=ttl,
                        )
                    except Exception as exc:
                        log.debug("redis_cache_write_failed", error=str(exc))

                log.debug(
                    "llm_call_complete",
                    label=str(label),
                    latency_ms=response.latency_ms,
                )

                # 记录服务端缓存信息(客户端 cache miss 后 provider 返回的 cache 命中情况)
                cache_usage = response.cache_usage
                cache_hit_tokens = cache_usage.cache_hit_tokens if cache_usage else 0
                cache_miss_tokens = cache_usage.cache_miss_tokens if cache_usage else 0
                total_cache = cache_hit_tokens + cache_miss_tokens
                server_hit_rate = cache_hit_tokens / total_cache if total_cache > 0 else 0.0
                log.info(
                    "llm_cache_miss_with_server_info",
                    label=str(label),
                    server_cache_hit=cache_hit_tokens,
                    server_cache_miss=cache_miss_tokens,
                    server_hit_rate=server_hit_rate,
                )

                # 递增 Prometheus 服务端缓存指标
                if cache_hit_tokens > 0:
                    metrics.llm_server_cache_hit_tokens.labels(
                        call_point=cp.value, provider=label.provider
                    ).inc(cache_hit_tokens)
                if cache_miss_tokens > 0:
                    metrics.llm_server_cache_miss_tokens.labels(
                        call_point=cp.value, provider=label.provider
                    ).inc(cache_miss_tokens)

                # Prefix shape diagnostics: capture and compare prefix shape (pure observability)
                system_prompt = ""
                messages = payload.get("messages", [])
                for msg in messages:
                    if isinstance(msg, dict) and msg.get("role") == "system":
                        system_prompt = msg.get("content", "")
                        break
                tools_schema = payload.get("tools")

                prefix_hash, prefix_changed, change_reasons = (
                    self._prefix_tracker.compute_prefix_hash(
                        call_point=cp.value,
                        system_prompt=system_prompt,
                        payload=payload,
                        tools_schema=tools_schema,
                    )
                )
                self._prefix_tracker.update_cache_stats(
                    call_point=cp.value,
                    server_cache_hit=cache_hit_tokens,
                    server_cache_miss=cache_miss_tokens,
                )
                if prefix_changed:
                    log.info(
                        "llm_cache_miss_diagnosed",
                        call_point=cp.value,
                        change_reasons=change_reasons,
                        prefix_hash=prefix_hash,
                    )

                # 发射使用事件
                await self._emit_usage_event(
                    label=response.label,
                    call_point=cp,
                    latency_ms=response.latency_ms,
                    token_usage=response.token_usage,
                    success=True,
                    article_id=article_id,
                    task_id=task_id,
                )

                # 解析输出
                if output_model:
                    return parse_llm_json(response.content, output_model)

                return response.content

            except Exception as exc:
                last_error = exc
                log.error(
                    "provider_call_failed",
                    provider=label.provider,
                    label=str(label),
                    error=str(exc),
                )
                continue

        # 所有 provider 都失败
        await self._emit_usage_event(
            label=parsed_label,
            call_point=cp,
            latency_ms=0.0,
            token_usage=None,
            success=False,
            error_type=type(last_error).__name__ if last_error else "NoProviderAvailable",
            article_id=article_id,
            task_id=task_id,
        )
        if last_error is not None:
            raise last_error
        raise AllProvidersFailedError(
            labels=labels,
            last_error=None,
            message=f"No available provider for label: {parsed_label}",
        )

    async def batch_call(
        self,
        label: str | Label,
        payloads: list[dict[str, Any]],
        call_point: CallPoint | str,
        fallback_labels: list[str | Label] | None = None,
        output_model: type[T] | None = None,
        timeout: float | None = None,
    ) -> list[T | str]:
        """Batch LLM call using Redis MGET/MSET for cache efficiency.

        Checks all cache keys in a single MGET call, then only calls
        the LLM for uncached items, and stores results via MSET.

        Args:
            label: 标签或标签字符串
            payloads: 调用参数列表
            call_point: 调用点标识
            fallback_labels: 备用标签列表
            output_model: 可选的Pydantic模型
            timeout: 超时覆盖

        Returns:
            结果列表，顺序与 payloads 对应
        """
        if isinstance(call_point, str):
            try:
                cp = CallPoint(call_point)
            except ValueError:
                cp = CallPoint.CLASSIFIER
        else:
            cp = call_point

        ttl = CACHE_TTL.get(cp.value, CACHE_TTL["default"])

        # Generate cache keys for all payloads
        cache_keys = [
            f"cache:llm:{cp.value}:{hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
            for p in payloads
        ]

        # Batch cache lookup via MGET
        results: list[T | str | None] = [None] * len(payloads)
        uncached_indices: list[int] = []

        if self._redis:
            try:
                cached_values = await self._redis.mget(cache_keys)
                for i, cached in enumerate(cached_values):
                    if cached:
                        data = json.loads(cached)
                        content = data["content"]
                        if output_model:
                            results[i] = parse_llm_json(content, output_model)
                        else:
                            results[i] = content
                        self._cache_hits += 1
                    else:
                        uncached_indices.append(i)
            except Exception as exc:
                log.debug("batch_cache_mget_failed", error=str(exc))
                uncached_indices = list(range(len(payloads)))
        else:
            uncached_indices = list(range(len(payloads)))

        # Call LLM for uncached items
        if uncached_indices:
            uncached_results: dict[int, T | str] = {}
            for idx in uncached_indices:
                try:
                    result = await self.call(
                        label=label,
                        payload=payloads[idx],
                        call_point=cp,
                        fallback_labels=fallback_labels,
                        output_model=output_model,
                        timeout=timeout,
                    )
                    uncached_results[idx] = result
                    results[idx] = result
                except Exception:
                    raise

            # Store uncached results via MSET
            if self._redis and uncached_results:
                try:
                    mapping: dict[str, str] = {}
                    for idx, result in uncached_results.items():
                        content = (
                            result
                            if isinstance(result, str)
                            else json.dumps(result, ensure_ascii=False)
                        )
                        mapping[cache_keys[idx]] = json.dumps(
                            {"content": content},
                            ensure_ascii=False,
                        )
                    if mapping:
                        await self._redis.mset(mapping)
                        # Set TTL for each key
                        for key in mapping:
                            with contextlib.suppress(Exception):
                                await self._redis.expire(key, ttl)
                except Exception as exc:
                    log.debug("batch_cache_mset_failed", error=str(exc))

        return results  # type: ignore[return-value]

    async def call_at(
        self,
        call_point: str,
        payload: dict[str, Any],
        output_model: type[T] | None = None,
        timeout: float | None = None,
        article_id: str | None = None,
        task_id: str | None = None,
    ) -> T | str:
        """通过调用点配置路由.

        Args:
            call_point: 调用点名称
            payload: 调用参数
            output_model: 可选的Pydantic模型
            timeout: 超时覆盖
            article_id: 关联的文章ID（用于LLM调用追踪）
            task_id: 关联的任务ID（用于LLM调用追踪）

        Returns:
            解析后的模型实例或原始字符串
        """
        # Use SmartRouter if configured, fallback to static LabelRouter
        if self._smart_router:
            labels = self._smart_router.route(call_point)
        else:
            labels = self._router.get_call_point_route(call_point)
        if not labels:
            raise ValueError(f"Call point not configured: {call_point}")

        # TieredRouter: difficulty-based routing overrides label selection
        tiered_label = self._try_tiered_routing(call_point, payload)
        if tiered_label is not None:
            labels = [tiered_label]

        # 构建请求payload
        request_payload = dict(payload)

        # Apply call-point level overrides (think, max_tokens, temperature)
        cp_config = self._router.get_call_point_config(
            call_point.value if isinstance(call_point, CallPoint) else call_point
        )
        if cp_config:
            if cp_config.think is not None and "think" not in request_payload:
                request_payload["think"] = cp_config.think
            if cp_config.max_tokens is not None and "max_tokens" not in request_payload:
                request_payload["max_tokens"] = cp_config.max_tokens
            if cp_config.temperature is not None and "temperature" not in request_payload:
                request_payload["temperature"] = cp_config.temperature
            if cp_config.response_format is not None and "response_format" not in request_payload:
                request_payload["response_format"] = cp_config.response_format

        # 如果有prompt_loader,构建system_prompt
        if self._prompts:
            # Extract string value from CallPoint enum if needed
            prompt_name = call_point.value if isinstance(call_point, CallPoint) else str(call_point)
            system_prompt = self._prompts.get(prompt_name)
            current_time = get_current_time_with_timezone()
            system_prompt = f"当前时间: {current_time}\n\n{system_prompt}"

            # 构建user_content
            user_content = json.dumps(payload, ensure_ascii=False, default=str)

            # 处理retry hint
            if "_retry_hint" in request_payload:
                system_prompt += f"\n\n{request_payload.pop('_retry_hint')}"

            # Preserve call-point overrides (think, max_tokens, temperature, response_format)
            preserved_overrides = {
                k: request_payload[k]
                for k in ("think", "max_tokens", "temperature", "response_format")
                if k in request_payload
            }

            request_payload = {
                "system_prompt": system_prompt,
                "user_content": user_content,
                **preserved_overrides,  # Merge back overrides
            }

        result = await self.call(
            labels[0],
            request_payload,
            call_point=call_point,
            article_id=article_id,
            task_id=task_id,
            fallback_labels=labels[1:],
            output_model=output_model,
            timeout=timeout,
        )

        # Trigger shadow evaluation if enabled
        if self._eval_runner and self._eval_runner.should_trigger(call_point):
            cp_str = call_point.value if isinstance(call_point, CallPoint) else call_point
            await self._eval_runner.trigger_shadow_call(
                call_point=cp_str,
                primary_label=labels[0],
                primary_result=result,
                primary_latency=0.0,  # Already captured in the call
                primary_success=True,
                primary_tokens=TokenUsage(),
                payload=request_payload,
            )

        return result

    def _try_tiered_routing(
        self, call_point: str | CallPoint, payload: dict[str, Any]
    ) -> Label | None:
        """Try difficulty-based tiered routing for this call point.

        Returns a Label if tiered routing is enabled and configured
        for this call point, otherwise None (fall through to SmartRouter).

        Args:
            call_point: Call point name.
            payload: Request payload (used to extract text for difficulty estimation).

        Returns:
            Label from tiered routing, or None.
        """
        if self._tiered_router is None:
            return None

        cp_str = call_point.value if isinstance(call_point, CallPoint) else str(call_point)

        # Check if tiered routing is enabled for this call point
        cp_config = self._router.get_call_point_config(cp_str)
        if cp_config is None or not cp_config.tiered_routing:
            return None

        # Extract text from payload for difficulty estimation
        text = payload.get("body", payload.get("user_content", ""))
        if not text:
            return None

        entity_count = payload.get("entity_count", 0)
        label = self._tiered_router.route(cp_str, text, entity_count=entity_count)
        if label is not None:
            log.debug(
                "tiered_routing_selected",
                call_point=cp_str,
                label=str(label),
            )
        return label

    async def embed(
        self,
        label: str | Label,
        texts: list[str],
        batch_size: int = 32,
        use_cache: bool = True,
        article_id: str | None = None,
        task_id: str | None = None,
    ) -> list[list[float]]:
        """生成embedding向量.

        Args:
            label: 标签
            texts: 文本列表
            batch_size: 批处理大小
            use_cache: 是否使用缓存
            article_id: 关联的文章ID（用于LLM调用追踪）
            task_id: 关联的任务ID（用于LLM调用追踪）

        Returns:
            embedding向量列表
        """
        parsed_label = Label.parse(label) if isinstance(label, str) else label

        if parsed_label.llm_type != LLMType.EMBEDDING:
            raise ValueError(f"Label must be embedding type, got: {parsed_label.llm_type}")

        all_embeddings: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # 检查缓存 (batch MGET)
        if use_cache and self._redis:
            cache_keys = [self._make_cache_key(text) for text in texts]
            try:
                cached_values = await self._redis.mget(cache_keys)
                for i, cached in enumerate(cached_values):
                    if cached:
                        all_embeddings[i] = json.loads(cached)
                    else:
                        uncached_indices.append(i)
                        uncached_texts.append(texts[i])
            except Exception as exc:
                log.debug("embedding_cache_batch_read_failed", error=str(exc))
                uncached_indices = list(range(len(texts)))
                uncached_texts = texts
        else:
            uncached_indices = list(range(len(texts)))
            uncached_texts = texts

        # 计算未缓存的embedding
        if uncached_texts:
            new_embeddings: list[list[float]] = []

            for i in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[i : i + batch_size]
                response = await self.call(
                    parsed_label,
                    {"texts": batch},
                    call_point=CallPoint.EMBEDDING,
                    article_id=article_id,
                    task_id=task_id,
                )
                new_embeddings.extend(response)

            # 存储到缓存并填充结果
            for idx, embedding in zip(uncached_indices, new_embeddings):
                all_embeddings[idx] = embedding
                if use_cache and self._redis and embedding:
                    cache_key = self._make_cache_key(texts[idx])
                    try:
                        await self._redis.set(
                            cache_key,
                            json.dumps(embedding),
                            ex=EMBEDDING_CACHE_TTL,
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

        # 返回结果,未计算的返回零向量
        return [e or [0.0] * 1024 for e in all_embeddings]

    async def embed_default(
        self,
        texts: list[str],
        batch_size: int = 32,
        use_cache: bool = True,
        article_id: str | None = None,
        task_id: str | None = None,
    ) -> list[list[float]]:
        """使用默认provider生成embedding.

        Args:
            texts: 文本列表
            batch_size: 批处理大小
            use_cache: 是否使用缓存
            article_id: 关联的文章ID（用于LLM调用追踪）
            task_id: 关联的任务ID（用于LLM调用追踪）

        Returns:
            embedding向量列表
        """
        label = self._router.get_default(LLMType.EMBEDDING)
        return await self.embed(
            label, texts, batch_size, use_cache, article_id=article_id, task_id=task_id
        )

    async def rerank(
        self,
        label: str | Label,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rerank文档.

        Args:
            label: 标签
            query: 查询文本
            documents: 文档列表
            top_n: 返回数量

        Returns:
            rerank结果列表 [{"index": int, "score": float}, ...]
        """
        parsed_label = Label.parse(label) if isinstance(label, str) else label

        if parsed_label.llm_type != LLMType.RERANK:
            raise ValueError(f"Label must be rerank type, got: {parsed_label.llm_type}")

        response = await self.call(
            parsed_label,
            {
                "query": query,
                "documents": documents,
                "top_n": top_n or len(documents),
            },
            call_point=CallPoint.RERANK,
        )

        log.debug(
            "rerank_complete",
            label=str(parsed_label),
            num_documents=len(documents),
        )

        return response

    async def rerank_default(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """使用默认provider进行rerank.

        Args:
            query: 查询文本
            documents: 文档列表
            top_n: 返回数量

        Returns:
            rerank结果列表
        """
        label = self._router.get_default(LLMType.RERANK)
        return await self.rerank(label, query, documents, top_n)

    def _make_cache_key(self, text: str) -> str:
        """生成缓存key."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
        return f"{EMBEDDING_CACHE_PREFIX}{text_hash}"

    def _build_cache_key(self, call_point: str, payload: dict[str, Any]) -> str:
        """Build cache key with grayscale switch for v2 stable key.

        When LLM_CACHE_KEY_V2_ENABLED=true, uses build_stable_cache_key
        which excludes non-semantic fields. Otherwise uses the legacy
        exact-hash behavior.

        Args:
            call_point: The call point identifier.
            payload: The request payload.

        Returns:
            Cache key string.
        """
        if os.getenv("LLM_CACHE_KEY_V2_ENABLED", "false").lower() == "true":
            return build_stable_cache_key(call_point, payload)

        return f"cache:llm:{call_point}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """获取所有provider的监控指标."""
        metrics = {name: pool.get_metrics() for name, pool in self._pools.items()}
        metrics["cache"] = {
            "size": len(self._response_cache),
            "maxsize": self._response_cache.maxsize,
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": (
                self._cache_hits / (self._cache_hits + self._cache_misses)
                if (self._cache_hits + self._cache_misses) > 0
                else 0.0
            ),
        }
        return metrics

    def get_pool(self, name: str) -> ProviderPool | None:
        """获取provider池."""
        return self._pools.get(name)

    def list_providers(self) -> list[str]:
        """列出所有provider."""
        return list(self._pools.keys())

    @classmethod
    async def create_from_settings(
        cls,
        llm_settings: Any,  # LLMSettings
        event_bus: EventBus,
        cache_client: Any = None,
        prompt_loader: PromptLoader | None = None,
    ) -> LLMClient:
        """从LLMSettings创建客户端.

        Args:
            llm_settings: LLMSettings实例
            event_bus: 事件总线(必需)
            cache_client: 可选的Redis客户端
            prompt_loader: 可选的Prompt加载器

        Returns:
            配置好的LLMClient实例
        """
        providers = list(llm_settings.providers.values())
        global_config = GlobalConfig(
            circuit_breaker_threshold=llm_settings.circuit_breaker_threshold,
            circuit_breaker_timeout=llm_settings.circuit_breaker_timeout,
            default_timeout=llm_settings.default_timeout,
            defaults=llm_settings.defaults,
            call_points=llm_settings.call_points,
        )
        return cls(providers, global_config, event_bus, cache_client, prompt_loader)
