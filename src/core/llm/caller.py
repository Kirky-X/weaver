# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LiteLLM unified caller for all LLM operations."""

from __future__ import annotations

import time
from typing import Any

import httpx
from litellm import acompletion, aembedding, arerank
from openai import AsyncOpenAI

from core.llm.types import Label, LLMResponse, LLMType, TokenUsage
from core.observability.logging import get_logger

log = get_logger("litellm_caller")

# LiteLLM原生支持的rerank provider类型
LITELLM_RERANK_PROVIDERS = frozenset({"cohere", "huggingface", "jina", "infinity"})


class LiteLLMCaller:
    """LiteLLM统一调用封装.

    提供统一的chat、embedding、rerank调用接口.
    """

    def __init__(self) -> None:
        """初始化caller."""

    @staticmethod
    def _build_model_name(provider_type: str, model_id: str) -> str:
        """构建LiteLLM格式的模型名称.

        Args:
            provider_type: LiteLLM provider类型 (openai, anthropic等)
            model_id: 模型ID

        Returns:
            LiteLLM格式模型名，如 "openai/gpt-4o"
        """
        return f"{provider_type}/{model_id}"

    async def chat(
        self,
        label: Label,
        provider_type: str,
        api_key: str,
        api_base: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ) -> LLMResponse:
        """执行chat调用.

        Args:
            label: 调用标签
            provider_type: LiteLLM provider类型
            api_key: API密钥
            api_base: API基础URL
            system_prompt: 系统提示
            user_content: 用户内容
            temperature: 采样温度
            max_tokens: 最大token数
            timeout: 超时时间

        Returns:
            LLM响应
        """
        model = self._build_model_name(provider_type, label.model)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        start_time = time.monotonic()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "api_key": api_key,
            "temperature": temperature,
            "timeout": timeout,
        }

        if api_base:
            kwargs["api_base"] = api_base

        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await acompletion(**kwargs)

            latency_ms = (time.monotonic() - start_time) * 1000

            content = response.choices[0].message.content or ""

            if not content:
                log.warning(
                    "chat_empty_response",
                    model=model,
                    finish_reason=getattr(response.choices[0], "finish_reason", None),
                )

            usage = response.usage
            token_usage = TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            )

            log.debug(
                "chat_call_complete",
                model=model,
                latency_ms=latency_ms,
                input_tokens=token_usage.input_tokens,
                output_tokens=token_usage.output_tokens,
            )

            return LLMResponse(
                content=content,
                label=label,
                latency_ms=latency_ms,
                token_usage=token_usage,
                model=label.model,
            )

        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            log.error("chat_call_failed", model=model, error=str(exc))
            raise

    async def embed(
        self,
        label: Label,
        provider_type: str,
        api_key: str,
        api_base: str,
        texts: list[str],
        timeout: float = 30.0,
    ) -> LLMResponse:
        """执行embedding调用.

        Args:
            label: 调用标签
            provider_type: LiteLLM provider类型
            api_key: API密钥
            api_base: API基础URL
            texts: 文本列表
            timeout: 超时时间

        Returns:
            LLM响应，content为embedding向量列表
        """
        model = self._build_model_name(provider_type, label.model)

        start_time = time.monotonic()

        kwargs: dict[str, Any] = {
            "model": model,
            "input": texts,
            "api_key": api_key,
            "timeout": timeout,
        }

        if api_base:
            kwargs["api_base"] = api_base

        try:
            response = await aembedding(**kwargs)

            latency_ms = (time.monotonic() - start_time) * 1000

            # Handle both OpenAI SDK objects (has .embedding) and LiteLLM dicts (has ['embedding'])
            embeddings = [
                item.embedding if hasattr(item, "embedding") else item["embedding"]
                for item in response.data
            ]

            usage = response.usage
            token_usage = TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            )

            log.debug(
                "embed_call_complete",
                model=model,
                latency_ms=latency_ms,
                num_texts=len(texts),
            )

            return LLMResponse(
                content=embeddings,
                label=label,
                latency_ms=latency_ms,
                token_usage=token_usage,
                model=label.model,
            )

        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            log.error("embed_call_failed", model=model, error=str(exc))
            raise

    async def rerank(
        self,
        label: Label,
        provider_type: str,
        api_key: str,
        api_base: str,
        query: str,
        documents: list[str],
        top_n: int | None = None,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """执行rerank调用.

        对于LiteLLM支持的provider类型（cohere, huggingface等）使用LiteLLM。
        对于OpenAI兼容的rerank API，使用自定义HTTP调用。

        Args:
            label: 调用标签
            provider_type: provider类型
            api_key: API密钥
            api_base: API基础URL
            query: 查询文本
            documents: 文档列表
            top_n: 返回数量
            timeout: 超时时间

        Returns:
            LLM响应，content为rerank结果列表
        """
        top_n = top_n or len(documents)
        start_time = time.monotonic()

        try:
            # LiteLLM支持的provider使用原生arerank
            if provider_type in LITELLM_RERANK_PROVIDERS:
                model = f"{provider_type}/{label.model}"
                kwargs: dict[str, Any] = {
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                    "api_key": api_key,
                    "timeout": timeout,
                }
                if api_base:
                    kwargs["api_base"] = api_base

                response = await arerank(**kwargs)
                results = [{"index": r.index, "score": r.relevance_score} for r in response.results]
            else:
                # OpenAI兼容的rerank API使用自定义HTTP调用
                results = await self._rerank_openai_compatible(
                    api_base=api_base,
                    api_key=api_key,
                    model=label.model,
                    query=query,
                    documents=documents,
                    top_n=top_n,
                    timeout=timeout,
                )

            latency_ms = (time.monotonic() - start_time) * 1000

            log.debug(
                "rerank_call_complete",
                provider_type=provider_type,
                model=label.model,
                latency_ms=latency_ms,
                num_documents=len(documents),
                top_n=top_n,
            )

            return LLMResponse(
                content=results,
                label=label,
                latency_ms=latency_ms,
                token_usage=None,
                model=label.model,
            )

        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            log.error("rerank_call_failed", provider_type=provider_type, error=str(exc))
            raise

    async def _rerank_openai_compatible(
        self,
        api_base: str,
        api_key: str,
        model: str,
        query: str,
        documents: list[str],
        top_n: int,
        timeout: float,
    ) -> list[dict[str, Any]]:
        """使用 OpenAI 库调用 OpenAI 兼容的 rerank API.

        用于 aiping.cn 等 OpenAI 兼容的 rerank API。
        使用 OpenAI 库的 client.post() 方法保持依赖一致性。

        Args:
            api_base: API基础URL
            api_key: API密钥
            model: 模型ID
            query: 查询文本
            documents: 文档列表
            top_n: 返回数量
            timeout: 超时时间

        Returns:
            rerank结果列表 [{"index": int, "score": float}, ...]
        """
        if not documents:
            return []

        # 使用 OpenAI 库的 AsyncOpenAI 客户端
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base.rstrip("/"),
            timeout=timeout,
        )

        # 使用 client.post() 发送自定义请求
        response = await client.post(
            "/rerank",
            body={
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            cast_to=httpx.Response,
        )

        result: dict[str, Any] = response.json()
        api_results = result.get("results", [])

        return [
            {
                "index": item.get("index", i),
                "score": item.get("relevance_score", 0.0),
            }
            for i, item in enumerate(api_results)
            if i < top_n
        ]

    async def call(
        self,
        label: Label,
        provider_type: str,
        api_key: str,
        api_base: str,
        payload: dict[str, Any],
        timeout: float = 120.0,
    ) -> LLMResponse:
        """通用调用方法，根据label类型分发.

        Args:
            label: 调用标签
            provider_type: LiteLLM provider类型
            api_key: API密钥
            api_base: API基础URL
            payload: 调用参数
            timeout: 超时时间

        Returns:
            LLM响应
        """
        if label.llm_type == LLMType.CHAT:
            return await self.chat(
                label=label,
                provider_type=provider_type,
                api_key=api_key,
                api_base=api_base,
                system_prompt=payload.get("system_prompt", ""),
                user_content=payload.get("user_content", ""),
                temperature=payload.get("temperature", 0.0),
                max_tokens=payload.get("max_tokens"),
                timeout=timeout,
            )
        elif label.llm_type == LLMType.EMBEDDING:
            return await self.embed(
                label=label,
                provider_type=provider_type,
                api_key=api_key,
                api_base=api_base,
                texts=payload.get("texts", []),
                timeout=timeout,
            )
        elif label.llm_type == LLMType.RERANK:
            return await self.rerank(
                label=label,
                provider_type=provider_type,
                api_key=api_key,
                api_base=api_base,
                query=payload.get("query", ""),
                documents=payload.get("documents", []),
                top_n=payload.get("top_n"),
                timeout=timeout,
            )
        else:
            raise ValueError(f"Unknown LLM type: {label.llm_type}")
