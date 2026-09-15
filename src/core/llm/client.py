# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unified LLM client with label-based routing."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from typing import TYPE_CHECKING, Any, TypeVar, cast

import jsonschema
from cachetools import TTLCache
from pydantic import BaseModel

from core.constants import RedisKeys
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
from core.utils.time_utils import get_current_date, get_current_time_with_timezone

if TYPE_CHECKING:
    from core.event import EventBus
    from core.llm.cost.calculator import CostCalculator
    from core.llm.evaluation.eval_runner import EvalRunner
    from core.llm.routing.smart_router import SmartRouter
    from core.llm.routing.tiered_router import TieredRouter
    from core.prompt.loader import PromptLoader
    from core.protocols import GraphPool

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class _ProviderFailed:
    """Sentinel returned by _execute_single_provider on failure."""

    def __init__(self, error: Exception | None) -> None:
        self.error = error


_PROVIDER_FAILED = _ProviderFailed(None)

# 结构化输出（output_model 存在）时追加到 system_prompt 最末尾的格式约束。
# 利用弱模型 recency bias（对末尾指令记忆最强），强制 JSON-only 输出。
# 集中在 client.py 而非每个 prompt 文件，确保所有结构化 CallPoint 统一兜底（DRY）。
_JSON_FORMAT_TAIL = """

【输出格式·强制】
仅输出一个 JSON 对象：首字符必须是 "{"，末字符必须是 "}"。
禁止 ```代码块``` 围栏、禁止任何解释/前言/结语、禁止 JSON 以外任何文字。"""

# Fields that do not affect LLM output semantics.
# Changes to these fields should NOT invalidate the cache.
NON_SEMANTIC_FIELDS: frozenset[str] = frozenset(
    {
        "article_id",
        "task_id",
        "timestamp",
        "request_id",
        "trace_id",
    }
)


def build_stable_cache_key(call_point: str, payload: dict[str, Any]) -> str:
    """Build a stable cache key excluding non-semantic fields.

    Removes non-semantic fields (article_id, task_id, timestamp, etc.)
    from the payload, then generates a normalized hash. This ensures
    that changes to tracking metadata do not invalidate the cache when
    the semantic content is unchanged.

    Args:
        call_point: The call point identifier (e.g., "classifier").
        payload: The request payload dictionary.

    Returns:
        Cache key in format: cache:llm:v2:{call_point}:{sha256[:16]}
    """
    semantic_payload = {k: v for k, v in payload.items() if k not in NON_SEMANTIC_FIELDS}
    normalized = json.dumps(semantic_payload, sort_keys=True, ensure_ascii=False, default=str)
    stable_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"cache:llm:v2:{call_point}:{stable_hash}"


# Embedding cache settings
# NOTE: ``emb:`` is deliberately disjoint from the LLM response-cache namespace
# ``cache:llm:v2:`` (see _make_llm_cache_key). The generic ``call()`` cache-read
# path does ``json.loads(cached)["content"]``, which assumes a JSON object — an
# embedding entry is a bare JSON list, so any overlap would raise
# TypeError/KeyError. Keep these prefixes distinct (OCR LOW #131).
EMBEDDING_CACHE_PREFIX = RedisKeys.EMBEDDING_PREFIX
EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days

# Input limits per call point (in characters)
_INPUT_LIMITS: dict[str, int] = {
    "classifier": 600,
    "categorizer": 1100,
    "quality_scorer": 1500,
    "credibility_checker": 2000,
    "analyze": 3000,
    # 合并调用点沿用 narrative 侧 8000 预算（narrative 8000 > analyze 3000，
    # 取宽者；TOML [input_limits] 可覆盖）
    "analyze_narrative": 8000,
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
        graph_pool: GraphPool | None = None,
        cost_calculator: CostCalculator | None = None,
        input_limits: dict[str, int] | None = None,
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
            graph_pool: 可选的图数据库池（用于structured_call schema查询）.
                container 在创建实例后也可通过属性赋值注入（mirrors
                _smart_router 模式，lifecycle.py:194）.
            cost_calculator: 可选的成本计算器.
                当传入时, _emit_usage_event 会计算 cost_usd 并填入 LLMUsageEvent;
                None 时 cost_usd 保持 0.0 (向后兼容).
        """
        self._global_config = global_config
        self._router = LabelRouter(global_config)
        self._smart_router = smart_router
        self._eval_runner = eval_runner
        self._tiered_router = tiered_router
        self._redis = cache_client
        self._prompts = prompt_loader
        self._event_bus = event_bus
        # GraphPool for schema-driven structured output.
        # Construct-injected OR lazy-injected by container/lifecycle.py
        # (mirrors _smart_router pattern). None means caller has not wired a
        # graph pool — structured_call raises ValueError on use (Rule 12).
        self._graph_pool: GraphPool | None = graph_pool
        # CostCalculator for LLM usage accounting. None means caller has
        # not wired a calculator — cost_usd stays 0.0 in LLMUsageEvent.
        self._cost_calculator: CostCalculator | None = cost_calculator

        self._response_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1000, ttl=3600)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        # Schema cache for structured_call.
        # Avoids repeated graph DB roundtrips when same schema_node_id is
        # queried multiple times. SchemaNode is updated by NarrativeSchemaExtractorNode
        # occasionally; 5-minute TTL is a reasonable freshness/perf tradeoff.
        # Key: schema_node_id; Value: schema dict returned by get_schema.
        self._schema_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=64, ttl=300)

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

        # Per-call-point input truncation limits (characters); injectable so
        # deployments can tune the prompt budget without code changes.
        self._input_limits = dict(_INPUT_LIMITS)
        if input_limits:
            self._input_limits.update(input_limits)

        log.info(
            "llm_client_initialized",
            providers=list(self._pools.keys()),
        )

    @property
    def default_embedding_label(self) -> str:
        """Return the default embedding model label string."""
        return str(self._router.get_default(LLMType.EMBEDDING))

    @property
    def default_chat_label(self) -> str:
        """Return the default chat model label string.

        Sourced from llm.toml ``[defaults.chat]`` — components must use this
        instead of hardcoding provider-specific labels so the router
        configuration stays the single source of truth.
        """
        return str(self._router.get_default(LLMType.CHAT))

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

            # Cache str(label) once — used in cost calc, event, and logs.
            label_str = str(label)

            # Compute cost_usd when a CostCalculator is wired. Failures are
            # logged, metric'd, and degraded to 0.0 — cost accounting must
            # never block the usage event (Rule 12 fail-loud via metric).
            cost_usd = 0.0
            if self._cost_calculator is not None and token_usage is not None:
                try:
                    cost_usd = self._cost_calculator.calculate(
                        label=label_str,
                        tokens=token_usage,
                    )
                except Exception as calc_exc:
                    log.warning(
                        "cost_calculation_failed",
                        label=label_str,
                        error=str(calc_exc),
                        error_type=type(calc_exc).__name__,
                    )
                    metrics.llm_cost_calculation_failures.labels(
                        call_point=call_point.value,
                        error_type=type(calc_exc).__name__,
                    ).inc()

            event = LLMUsageEvent(
                label=label_str,
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
                cost_usd=cost_usd,
            )
            await self._event_bus.publish(event)

            # Accumulate cost metric for observability.
            if cost_usd > 0.0:
                metrics.llm_cost_usd_total.labels(
                    call_point=call_point.value,
                    provider=label.provider,
                    model=label.model,
                ).inc(cost_usd)
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
        cp = self._resolve_call_point(call_point)

        cache_key = self._build_cache_key(cp.value, payload)
        ttl = CACHE_TTL.get(cp.value, CACHE_TTL["default"])

        # Cache lookup (Redis → TTLCache)
        cached = await self._check_response_cache(cache_key, parsed_label, output_model)
        if cached is not None:
            return cached

        log.debug("llm_cache_miss", label=str(parsed_label))
        self._cache_misses += 1

        truncated_payload = self._truncate_payload_for_callpoint(payload, cp)

        # 构建label链
        labels = self._router.resolve(parsed_label)
        if fallback_labels:
            for fb in fallback_labels:
                fb_label = Label.parse(fb) if isinstance(fb, str) else fb
                if fb_label not in labels:
                    labels.append(fb_label)

        # 按 provider 分组 labels, 执行跨池 fallback
        last_error: Exception | None = None
        for lbl in labels:
            result = await self._execute_single_provider(
                lbl,
                truncated_payload,
                cp,
                cache_key,
                ttl,
                timeout,
                article_id,
                task_id,
                output_model,
                payload,
            )
            if not isinstance(result, _ProviderFailed):
                return result
            last_error = result.error
            # 本 provider 失败后还有候选 → 记一次真实 fallback（可观测性：
            # 优化前此路径零指标，故障只能事后翻 DB）。
            if lbl is not labels[-1]:
                metrics.fallback_total.labels(
                    call_point=cp.value,
                    from_provider=lbl.provider,
                    reason=type(last_error).__name__ if last_error else "unknown",
                ).inc()

        # 所有 provider 都失败
        await self._handle_all_providers_failed(
            parsed_label,
            cp,
            last_error,
            labels,
            article_id,
            task_id,
        )
        # Unreachable: the handler above always raises.
        raise AllProvidersFailedError(f"all provider candidates failed for {cp.value}")

    def _resolve_call_point(self, call_point: CallPoint | str) -> CallPoint:
        """Parse and validate call point."""
        if isinstance(call_point, str):
            try:
                return CallPoint(call_point)
            except ValueError:
                log.warning(
                    "invalid_call_point",
                    call_point=call_point,
                    fallback="CLASSIFIER",
                )
                return CallPoint.CLASSIFIER
        return call_point

    async def _check_response_cache(
        self,
        cache_key: str,
        parsed_label: Label,
        output_model: type[T] | None,
    ) -> T | str | None:
        """Check Redis then TTLCache for cached response. Returns None on miss."""
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

        return None

    def _truncate_payload_for_callpoint(
        self,
        payload: dict[str, Any],
        cp: CallPoint,
    ) -> dict[str, Any]:
        """Truncate input body based on call point limits."""
        if "body" not in payload:
            return payload
        truncated = dict(payload)
        limit = self._input_limits.get(cp.value, self._input_limits["default"])
        body = payload["body"]
        title = payload.get("title")
        if title:
            truncated["body"] = f"标题：{title}\n\n正文：{body[:limit]}"
        else:
            truncated["body"] = body[:limit]
        return truncated

    async def _execute_single_provider(
        self,
        label: Label,
        truncated_payload: dict[str, Any],
        cp: CallPoint,
        cache_key: str,
        ttl: int,
        timeout: float | None,
        article_id: str | None,
        task_id: str | None,
        output_model: type[T] | None,
        original_payload: dict[str, Any],
    ) -> T | str | _ProviderFailed:
        """Execute a single provider label. Returns result or _ProviderFailed sentinel."""
        pool = self._pools.get(label.provider)
        if not pool:
            log.warning(
                "provider_pool_not_found",
                provider=label.provider,
                label=str(label),
            )
            return _ProviderFailed(None)

        started = time.monotonic()
        try:
            response = await pool.execute(
                labels=[label],
                payload=truncated_payload,
                call_point=cp.value,
                timeout=timeout,
                article_id=article_id,
                task_id=task_id,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            metrics.llm_call_total.labels(
                call_point=cp.value,
                provider=label.provider,
                status="error",
            ).inc()
            metrics.llm_call_latency.labels(
                call_point=cp.value,
                provider=label.provider,
            ).observe(elapsed)
            log.error(
                "provider_call_failed",
                provider=label.provider,
                label=str(label),
                error=str(exc),
            )
            return _ProviderFailed(exc)

        metrics.llm_call_total.labels(
            call_point=cp.value,
            provider=label.provider,
            status="success",
        ).inc()
        metrics.llm_call_latency.labels(
            call_point=cp.value,
            provider=label.provider,
        ).observe(time.monotonic() - started)

        # Cache write + metrics + diagnostics + usage event
        self._response_cache[cache_key] = {
            "content": response.content,
            "token_usage": response.token_usage,
        }
        await self._write_redis_cache(cache_key, response, ttl)
        self._record_server_cache_metrics(label, response, cp)
        self._record_prefix_diagnostics(label, response, cp, original_payload)

        await self._emit_usage_event(
            label=response.label,
            call_point=cp,
            latency_ms=response.latency_ms,
            token_usage=response.token_usage,
            success=True,
            article_id=article_id,
            task_id=task_id,
        )

        if output_model:
            return parse_llm_json(response.content, output_model)
        return response.content

    async def _write_redis_cache(self, cache_key: str, response: Any, ttl: int) -> None:
        """Write response to Redis cache (best-effort)."""
        if not self._redis:
            return
        try:
            token_usage_dict = {
                "input_tokens": response.token_usage.input_tokens if response.token_usage else 0,
                "output_tokens": response.token_usage.output_tokens if response.token_usage else 0,
                "total_tokens": response.token_usage.total_tokens if response.token_usage else 0,
            }
            await self._redis.set(
                cache_key,
                json.dumps(
                    {"content": response.content, "token_usage": token_usage_dict},
                    ensure_ascii=False,
                ),
                ex=ttl,
            )
        except Exception as exc:
            log.debug("redis_cache_write_failed", error=str(exc))

    def _record_server_cache_metrics(self, label: Label, response: Any, cp: CallPoint) -> None:
        """Record server-side cache metrics from provider response."""
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
        if cache_hit_tokens > 0:
            metrics.llm_server_cache_hit_tokens.labels(
                call_point=cp.value,
                provider=label.provider,
            ).inc(cache_hit_tokens)
        if cache_miss_tokens > 0:
            metrics.llm_server_cache_miss_tokens.labels(
                call_point=cp.value,
                provider=label.provider,
            ).inc(cache_miss_tokens)

    def _record_prefix_diagnostics(
        self,
        label: Label,
        response: Any,
        cp: CallPoint,
        payload: dict[str, Any],
    ) -> None:
        """Record prefix shape diagnostics (pure observability)."""
        cache_usage = response.cache_usage
        cache_hit_tokens = cache_usage.cache_hit_tokens if cache_usage else 0
        cache_miss_tokens = cache_usage.cache_miss_tokens if cache_usage else 0

        system_prompt = ""
        messages = payload.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break
        tools_schema = payload.get("tools")

        prefix_hash, prefix_changed, change_reasons = self._prefix_tracker.compute_prefix_hash(
            call_point=cp.value,
            system_prompt=system_prompt,
            payload=payload,
            tools_schema=tools_schema,
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

    async def _handle_all_providers_failed(
        self,
        parsed_label: Label,
        cp: CallPoint,
        last_error: Exception | None,
        labels: list,
        article_id: str | None,
        task_id: str | None,
    ) -> NoReturn:
        """Handle complete provider failure (always raises)."""
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
                # 与 call() 保持一致：非法 call_point 必须留可观测信号，
                # 否则 batch 路径会静默降级为 CLASSIFIER（OCR LOW #39）。
                log.warning(
                    "batch_call_point_invalid",
                    call_point=call_point,
                    fallback_call_point=CallPoint.CLASSIFIER.value,
                )
                cp = CallPoint.CLASSIFIER
        else:
            cp = call_point

        ttl = CACHE_TTL.get(cp.value, CACHE_TTL["default"])

        # Generate cache keys for all payloads — 与单次 call() 同源，
        # 避免 batch 路径 key 格式与灰度开关脱节。
        cache_keys = [self._build_cache_key(cp.value, p) for p in payloads]

        # Batch cache lookup via MGET.
        # 列表元素仅作为占位：下方每个下标要么命中缓存、要么由单次 call()
        # 填满（失败会直接抛异常），因此返回时不会再残留 None。
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
                # Preserve entries already parsed from cache before the
                # failure; only re-fetch the ones still missing so a single
                # corrupt cache entry does not defeat the whole cache.
                uncached_indices = [i for i, r in enumerate(results) if r is None]
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
                        if isinstance(result, str):
                            content = result
                        elif isinstance(result, BaseModel):
                            content = result.model_dump_json()
                        else:
                            content = json.dumps(result, ensure_ascii=False)
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
                    log.warning(
                        "batch_cache_mset_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )

        return cast(list[T | str], results)

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

        # NOTE: response_format intentionally NOT auto-enabled here. Some
        # OpenAI-compatible endpoints do not support the response_format
        # parameter and return empty responses when sent it. Prompts already
        # instruct JSON output.

        # 如果有prompt_loader,构建system_prompt
        if self._prompts:
            # Extract string value from CallPoint enum if needed
            prompt_name = call_point.value if isinstance(call_point, CallPoint) else str(call_point)
            system_prompt = self._prompts.get(prompt_name)
            # 日期锚定放在模板尾部而非前缀：秒级时间戳前缀会让 request_payload
            # 每秒变化 → 客户端缓存 key 永不命中，且服务端前缀缓存全 miss。
            # 日粒度 + 尾置使同日内 prompt 逐字节稳定，跨日自然轮换保留新鲜度。
            system_prompt = f"{system_prompt}\n\n当前日期: {get_current_date()}"

            # 构建user_content — 剥离 NON_SEMANTIC_FIELDS 使 cache key 稳定。
            # 追踪字段（article_id/task_id 等）不影响 LLM 输出语义，但若烘进
            # user_content 字符串，相同内容跨 article_id 会产生不同 cache key
            # → 永久 cache miss（重处理/相似内容无法复用）。
            semantic_payload = {k: v for k, v in payload.items() if k not in NON_SEMANTIC_FIELDS}
            user_content = json.dumps(semantic_payload, ensure_ascii=False, default=str)

            # 处理retry hint
            if "_retry_hint" in request_payload:
                system_prompt += f"\n\n{request_payload.pop('_retry_hint')}"

            # 结构化输出时追加 JSON 格式尾指令（放在最末尾，recency bias 最强）。
            # 纯文本 prompt（briefing/search 等）无 output_model，自动跳过避免污染。
            if output_model is not None:
                system_prompt += _JSON_FORMAT_TAIL

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

    def _get_first_label(self, call_point: CallPoint | str) -> Label:
        """Return the first routing label for ``call_point``.

        Uses SmartRouter if available, otherwise LabelRouter. Raises ValueError
        if no labels are configured — mirrors call_at behavior.

        Args:
            call_point: Call point name.

        Returns:
            First Label in the route.

        Raises:
            ValueError: If no labels are configured for the call point.
        """
        if self._smart_router:
            labels = self._smart_router.route(call_point)
        else:
            labels = self._router.get_call_point_route(call_point)
        if not labels:
            raise ValueError(f"Call point not configured: {call_point}")
        return labels[0]

    async def structured_call(
        self,
        prompt: str,
        schema_node_id: str,
        *,
        call_point: CallPoint | str | None = None,
        article_id: str | None = None,
        task_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Schema-driven structured output.

        Fetches the JSON Schema for ``schema_node_id`` from the graph database
        (SchemaDrivenStructuredOutput.get_schema), then calls the LLM with
        ``response_format=schema`` and validates the response.

        Two mutually-exclusive paths (priority):

        1. **SchemaNotFoundError path** (schema absent): degrade to a plain
           LLM call (no ``response_format``, no retry) and return
           ``{"_fallback": True, "content": <llm_response>}``. This is the
           ONLY fallback path — schema absence is a data problem, not a
           validation problem, so retry is meaningless.

        2. **Validation-retry path** (schema exists): call LLM with
           ``response_format=schema``. If response fails JSON Schema
           validation (jsonschema.validate raises ``ValidationError``) or
           is not valid JSON (``json.JSONDecodeError``), retry once with a
           ``_retry_hint`` appended to the prompt. If the retry also fails,
           raise ``StructuredOutputValidationError`` carrying ``schema`` and
           ``last_response`` for debugging.

        Args:
            prompt: User prompt for the LLM.
            schema_node_id: SchemaNode business-level id (format
                "schema-{event_type}", e.g. "schema-funding").
            call_point: Optional CallPoint for routing/tracing. Defaults
                to ``CallPoint.CLASSIFIER`` (structured extraction is
                typically a classification task).
            article_id: Optional article id for LLM call tracing.
            task_id: Optional task id for LLM call tracing.
            timeout: Optional per-call timeout override (seconds).

        Returns:
            - On success: the parsed JSON dict from the LLM response.
            - On SchemaNotFoundError: ``{"_fallback": True, "content": <str>}``
              where ``content`` is the raw LLM response (plain call, no
              schema enforcement).

        Raises:
            ValueError: If ``self._graph_pool`` is None (container did not
                inject a graph pool). Rule 12 fail-loud.
            StructuredOutputValidationError: If both the initial call and
                the retry fail JSON Schema validation (or are non-JSON).
                Carries ``schema`` and ``last_response`` attributes.
            Exception: GraphPool errors, LLM provider errors, etc.
                propagate (Rule 12 fail-loud).

        How to obtain ``schema_node_id``:

            SchemaNode records are written by ``NarrativeSchemaExtractorNode`` (pipeline
            phase3) via ``GraphWriter.merge_schema(event_type, pattern,
            confidence)``. The business-level id is deterministic and follows
            the format ``"schema-{event_type}"`` (e.g. ``"schema-funding"``,
            ``"schema-融资"``). Two ways to discover a valid id:

            1. **From pipeline state** (preferred when running inside a
               pipeline node): ``state["schema"]["schema_id"]`` is set by
               ``NarrativeSchemaExtractorNode`` after a successful MERGE.
            2. **From the graph database** (for ad-hoc / API callers):
               query ``MATCH (s:SchemaNode) RETURN s.id, s.event_type``
               via ``GraphPool.execute_query`` to enumerate available schemas.

            See ``docs/ARCHITECTURE.md`` § "Schema-Driven Structured Output"
            for the full data flow and SchemaNode field reference.

        Example::

            from core.llm.client import LLMClient
            from core.llm.structured_output import (
                SchemaNotFoundError,
                StructuredOutputValidationError,
            )

            llm = container.llm_client()  # _graph_pool injected by lifecycle.py
            try:
                result = await llm.structured_call(
                    prompt="分析本文的核心事件",
                    schema_node_id="schema-funding",
                    call_point=CallPoint.CLASSIFIER,
                    article_id="abc-123",
                )
                # result is a dict validated against the funding JSON Schema.
                print(result["event_type"], result.get("amount"))
            except SchemaNotFoundError:
                # Should not reach here — structured_call already degrades
                # internally to a plain call and returns ``{"_fallback": ...}``.
                # Catch only if you call SchemaDrivenStructuredOutput directly.
                pass
            except StructuredOutputValidationError as exc:
                # LLM response did not match schema after retry.
                # exc.schema  → the JSON Schema dict used for validation
                # exc.last_response → raw LLM response string from final attempt
                log.error(
                    "structured_call_failed",
                    schema_title=exc.schema.get("title"),
                    response_preview=exc.last_response[:200],
                )
                raise
            else:
                # Detect the fallback path (schema absent → plain call).
                if isinstance(result, dict) and result.get("_fallback"):
                    plain_text = result["content"]
                    # Caller decides: accept degraded output OR raise.

        """
        # Rule 12: fail-loud if container forgot to inject _graph_pool.
        # Mirrors _smart_router pattern: lazy attribute injection in
        # container/lifecycle.py:194.
        if self._graph_pool is None:
            raise ValueError(
                "structured_call requires _graph_pool to be injected "
                "(container/lifecycle.py). None means container wiring is "
                "missing or graph database is unavailable."
            )

        from core.llm.structured_output import (
            SchemaDrivenStructuredOutput,
            SchemaNotFoundError,
            StructuredOutputValidationError,
        )

        cp: CallPoint | str = call_point if call_point is not None else CallPoint.CLASSIFIER

        # Schema cache lookup (avoids graph DB roundtrip on repeated calls
        # with the same schema_node_id).
        # TTL is 5 minutes (set in __init__); SchemaNode updates are rare.
        cached_schema = self._schema_cache.get(schema_node_id)
        if cached_schema is not None:
            schema_result = cached_schema
        else:
            schema_provider = SchemaDrivenStructuredOutput(self._graph_pool)

            # Priority 1: SchemaNotFoundError → DIRECT fallback.
            # No retry — schema absence is a data problem, not validation.
            try:
                schema_result = await schema_provider.get_schema(schema_node_id)
            except SchemaNotFoundError:
                log.warning(
                    "structured_output_schema_not_found_degrade",
                    schema_node_id=schema_node_id,
                )
                fallback_payload: dict[str, Any] = {"user_content": prompt}
                # No response_format — plain call, schema absent.
                fallback_response = await self.call(
                    self._get_first_label(cp),
                    fallback_payload,
                    call_point=cp,
                    article_id=article_id,
                    task_id=task_id,
                    timeout=timeout,
                )
                return {"_fallback": True, "content": fallback_response}

            # Cache the fetched schema for subsequent calls.
            self._schema_cache[schema_node_id] = schema_result

        schema: dict[str, Any] = schema_result["schema"]

        # Priority 2: schema exists → retry path.
        # Call with response_format=schema; retry once on validation failure.
        # The violation hint is appended directly to the prompt — call()
        # (unlike call_at()) does not process a "_retry_hint" payload key,
        # so a hint placed there would silently never reach the model.
        schema_retry_hint = (
            "上一次响应不符合 JSON Schema 要求。"
            "请严格按 schema 输出，不要添加任何额外字段或解释文字。"
        )
        payloads = [
            {"user_content": prompt, "response_format": schema},
            {
                "user_content": f"{prompt}\n\n{schema_retry_hint}",
                "response_format": schema,
            },
        ]

        last_response: str = ""
        for attempt, payload in enumerate(payloads):
            response = await self.call(
                self._get_first_label(cp),
                payload,
                call_point=cp,
                article_id=article_id,
                task_id=task_id,
                timeout=timeout,
            )
            # Coerce to string — call() may return str or a BaseModel.
            if isinstance(response, str):
                last_response = response
            else:
                # Non-string response (e.g. BaseModel) — serialize to JSON.
                last_response = (
                    response.model_dump_json()
                    if hasattr(response, "model_dump_json")
                    else str(response)
                )

            try:
                parsed = json.loads(last_response)
            except json.JSONDecodeError as exc:
                log.warning(
                    "structured_output_invalid_json_retry",
                    schema_node_id=schema_node_id,
                    attempt=attempt,
                    error=str(exc),
                )
                # Continue to retry (or raise after last attempt below).
                continue

            try:
                jsonschema.validate(parsed, schema)
            except jsonschema.ValidationError as exc:
                log.warning(
                    "structured_output_schema_violation_retry",
                    schema_node_id=schema_node_id,
                    attempt=attempt,
                    error_path=list(exc.absolute_path),
                    error_message=exc.message,
                )
                # Continue to retry (or raise after last attempt below).
                continue

            # Validation passed.
            return parsed

        # Both attempts failed. Raise with diagnostic context.
        raise StructuredOutputValidationError(schema=schema, last_response=last_response)

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

        # Fail-loud: a missing or empty embedding must never be silently
        # substituted with a zero vector — zero vectors make all texts
        # equally (dis)similar and poison similarity search and entity
        # dedup once persisted. Surface the shortfall to the caller's
        # error handling instead.
        missing_indices = [i for i, e in enumerate(all_embeddings) if not e]
        if missing_indices:
            raise ValueError(
                f"embedding_result_incomplete: {len(missing_indices)}/{len(texts)} "
                f"embeddings missing (indices {missing_indices[:10]})"
            )

        return [e for e in all_embeddings if e is not None]

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
        # v2 默认开启（2026-09 翻转）：稳定 key 使重处理/相似内容复用缓存。
        # 显式设 LLM_CACHE_KEY_V2_ENABLED=false 可回退 legacy 格式（灰度保留）。
        if os.getenv("LLM_CACHE_KEY_V2_ENABLED", "true").lower() == "true":
            return build_stable_cache_key(call_point, payload)

        return f"cache:llm:{call_point}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()}"

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
        from core.llm.cost.calculator import CostCalculator

        providers = list(llm_settings.providers.values())
        global_config = GlobalConfig(
            circuit_breaker_threshold=llm_settings.circuit_breaker_threshold,
            circuit_breaker_timeout=llm_settings.circuit_breaker_timeout,
            default_timeout=llm_settings.default_timeout,
            defaults=llm_settings.defaults,
            call_points=llm_settings.call_points,
        )
        # Instantiate CostCalculator only when rates are configured.
        # Empty CostConfig (default) would compute cost_usd=0.0 for every
        # call — skip the work entirely. When rates exist, the calculator
        # computes real USD cost per LLM call.
        cost_calculator: CostCalculator | None = None
        if llm_settings.cost.rates:
            cost_calculator = CostCalculator(config=llm_settings.cost)
        return cls(
            providers,
            global_config,
            event_bus,
            cache_client,
            prompt_loader,
            cost_calculator=cost_calculator,
            input_limits=dict(getattr(llm_settings, "input_limits", None) or {}),
        )
