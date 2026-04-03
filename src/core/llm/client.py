# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unified LLM client with label-based routing."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from core.constants import RedisKeys
from core.llm.config import LLMConfigLoader
from core.llm.pool import ProviderPool
from core.llm.router import LabelRouter
from core.llm.types import (
    CallPoint,
    GlobalConfig,
    Label,
    LLMType,
    ProviderConfig,
)
from core.llm.utils.json_parser import parse_llm_json
from core.observability.logging import get_logger
from core.utils.time_utils import get_current_time_with_timezone

if TYPE_CHECKING:
    from core.prompt.loader import PromptLoader

log = get_logger("llm_client")

T = TypeVar("T", bound=BaseModel)

# Embedding cache settings
EMBEDDING_CACHE_PREFIX = RedisKeys.EMBEDDING_PREFIX
EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days


class LLMClient:
    """统一LLM调用入口.

    提供label路由、fallback、embedding缓存等功能.
    """

    def __init__(
        self,
        providers: list[ProviderConfig],
        global_config: GlobalConfig,
        redis_client: Any = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        """初始化LLM客户端.

        Args:
            providers: Provider配置列表
            global_config: 全局配置
            redis_client: 可选的Redis客户端（用于embedding缓存）
            prompt_loader: 可选的Prompt加载器（用于call_at方法）
        """
        self._global_config = global_config
        self._router = LabelRouter(global_config)
        self._redis = redis_client
        self._prompts = prompt_loader

        # 创建provider池映射
        self._pools: dict[str, ProviderPool] = {}
        for provider_cfg in providers:
            pool = ProviderPool(
                config=provider_cfg,
                circuit_breaker_threshold=global_config.circuit_breaker_threshold,
                circuit_breaker_timeout=global_config.circuit_breaker_timeout,
            )
            self._pools[provider_cfg.name] = pool

        log.info(
            "llm_client_initialized",
            providers=list(self._pools.keys()),
        )

    async def call(
        self,
        label: str | Label,
        payload: dict[str, Any],
        fallback_labels: list[str | Label] | None = None,
        output_model: type[T] | None = None,
        timeout: float | None = None,
    ) -> T | str:
        """通用LLM调用.

        Args:
            label: 标签或标签字符串
            payload: 调用参数
            fallback_labels: 备用标签列表
            output_model: 可选的Pydantic模型，用于结构化输出
            timeout: 超时覆盖

        Returns:
            解析后的模型实例或原始字符串
        """
        # 解析label
        parsed_label = Label.parse(label) if isinstance(label, str) else label

        # 构建label链
        labels = self._router.resolve(parsed_label)
        if fallback_labels:
            for fb in fallback_labels:
                fb_label = Label.parse(fb) if isinstance(fb, str) else fb
                if fb_label not in labels:
                    labels.append(fb_label)

        # 获取pool
        pool = self._pools.get(parsed_label.provider)
        if not pool:
            raise ValueError(f"Provider not found: {parsed_label.provider}")

        # 执行调用
        response = await pool.execute(labels, payload, timeout)

        log.debug(
            "llm_call_complete",
            label=str(parsed_label),
            latency_ms=response.latency_ms,
        )

        # 解析输出
        if output_model:
            return parse_llm_json(response.content, output_model)

        return response.content

    async def call_at(
        self,
        call_point: str,
        payload: dict[str, Any],
        output_model: type[T] | None = None,
        timeout: float | None = None,
    ) -> T | str:
        """通过调用点配置路由.

        Args:
            call_point: 调用点名称
            payload: 调用参数
            output_model: 可选的Pydantic模型
            timeout: 超时覆盖

        Returns:
            解析后的模型实例或原始字符串
        """
        labels = self._router.get_call_point_route(call_point)
        if not labels:
            raise ValueError(f"Call point not configured: {call_point}")

        # 构建请求payload
        request_payload = dict(payload)

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

            request_payload = {
                "system_prompt": system_prompt,
                "user_content": user_content,
            }

        return await self.call(labels[0], request_payload, labels[1:], output_model, timeout)

    async def embed(
        self,
        label: str | Label,
        texts: list[str],
        batch_size: int = 32,
        use_cache: bool = True,
    ) -> list[list[float]]:
        """生成embedding向量.

        Args:
            label: 标签
            texts: 文本列表
            batch_size: 批处理大小
            use_cache: 是否使用缓存

        Returns:
            embedding向量列表
        """
        parsed_label = Label.parse(label) if isinstance(label, str) else label

        if parsed_label.llm_type != LLMType.EMBEDDING:
            raise ValueError(f"Label must be embedding type, got: {parsed_label.llm_type}")

        all_embeddings: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # 检查缓存
        if use_cache and self._redis:
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

        # 计算未缓存的embedding
        if uncached_texts:
            new_embeddings: list[list[float]] = []

            for i in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[i : i + batch_size]
                response = await self.call(
                    parsed_label,
                    {"texts": batch},
                )
                new_embeddings.extend(response)

            # 存储到缓存并填充结果
            for idx, embedding in zip(uncached_indices, new_embeddings):
                all_embeddings[idx] = embedding
                if use_cache and self._redis and embedding:
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

        # 返回结果,未计算的返回零向量
        return [e or [0.0] * 1024 for e in all_embeddings]

    async def embed_default(
        self,
        texts: list[str],
        batch_size: int = 32,
        use_cache: bool = True,
    ) -> list[list[float]]:
        """使用默认provider生成embedding.

        Args:
            texts: 文本列表
            batch_size: 批处理大小
            use_cache: 是否使用缓存

        Returns:
            embedding向量列表
        """
        label = self._router.get_default(LLMType.EMBEDDING)
        return await self.embed(label, texts, batch_size, use_cache)

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

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """获取所有provider的监控指标."""
        return {name: pool.get_metrics() for name, pool in self._pools.items()}

    def get_pool(self, name: str) -> ProviderPool | None:
        """获取provider池."""
        return self._pools.get(name)

    def list_providers(self) -> list[str]:
        """列出所有provider."""
        return list(self._pools.keys())

    @classmethod
    async def create_from_config(
        cls,
        config_path: str,
        redis_client: Any = None,
        prompt_loader: PromptLoader | None = None,
    ) -> LLMClient:
        """从配置文件创建客户端.

        Args:
            config_path: 配置文件路径
            redis_client: 可选的Redis客户端
            prompt_loader: 可选的Prompt加载器

        Returns:
            配置好的LLMClient实例
        """
        providers, global_config = LLMConfigLoader.load(config_path)
        return cls(providers, global_config, redis_client, prompt_loader)
