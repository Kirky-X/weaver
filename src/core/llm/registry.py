# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Provider registry for dynamic LLM provider registration and discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from core.llm.types import LLMType
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.llm.providers.base import BaseLLMProvider

log = get_logger("provider_registry")


class ProviderCapability(str, Enum):
    """供应商能力标识。"""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VISION = "vision"
    FUNCTION_CALLING = "function_calling"
    STREAMING = "streaming"


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """供应商元信息。

    Attributes:
        name: 供应商类型名称
        display_name: 显示名称
        capabilities: 支持的能力集合
        default_base_url: 默认 API 端点
        default_model: 默认模型
        supports_custom_base_url: 是否支持自定义端点
        requires_api_key: 是否需要 API 密钥
    """

    name: str
    display_name: str
    capabilities: frozenset[ProviderCapability]
    default_base_url: str
    default_model: str
    supports_custom_base_url: bool = True
    requires_api_key: bool = True


class ProviderFactory(Protocol):
    """供应商工厂协议。"""

    def __call__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        extra_body: dict[str, Any] | None = None,
    ) -> BaseLLMProvider: ...


@dataclass
class ProviderInstanceConfig:
    """供应商实例配置。

    Attributes:
        name: 实例名称（在配置中唯一标识）
        provider_type: 供应商类型
        model: 模型名称
        api_key: API 密钥
        base_url: API 端点
        rpm_limit: 每分钟请求限制
        concurrency: 并发数
        timeout: 超时时间
        priority: 优先级（越低越优先）
        weight: 负载均衡权重
        capabilities: 能力集合
    """

    name: str
    provider_type: str
    model: str
    api_key: str = ""
    base_url: str = ""
    rpm_limit: int = 60
    concurrency: int = 5
    timeout: float = 120.0
    priority: int = 100
    weight: int = 100
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.CHAT})
    extra_body: dict[str, Any] = field(default_factory=dict)

    def supports(self, llm_type: LLMType) -> bool:
        """检查是否支持指定的 LLM 类型。"""
        type_to_capability = {
            LLMType.CHAT: ProviderCapability.CHAT,
            LLMType.EMBEDDING: ProviderCapability.EMBEDDING,
            LLMType.RERANK: ProviderCapability.RERANK,
        }
        return type_to_capability.get(llm_type) in self.capabilities


class ProviderNotFoundError(Exception):
    """供应商类型未找到异常。"""

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type
        super().__init__(f"Provider type not found: {provider_type}")


class ProviderRegistry:
    """供应商注册中心 - 管理所有已注册的供应商类型。

    支持运行时注册新供应商类型，实现供应商的插件化扩展。
    """

    _instance: ProviderRegistry | None = None

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._metadata: dict[str, ProviderMetadata] = {}
        self._register_builtin_providers()

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（用于测试）。"""
        cls._instance = None

    def register(
        self,
        provider_type: str,
        factory: ProviderFactory,
        metadata: ProviderMetadata,
    ) -> None:
        """注册一个新供应商类型。

        Args:
            provider_type: 供应商类型标识
            factory: 供应商工厂函数
            metadata: 供应商元信息
        """
        self._factories[provider_type] = factory
        self._metadata[provider_type] = metadata
        log.debug("provider_registered", provider_type=provider_type)

    def create_provider(
        self,
        config: ProviderInstanceConfig,
    ) -> BaseLLMProvider:
        """创建供应商实例。

        Args:
            config: 供应商实例配置

        Returns:
            供应商实例

        Raises:
            ProviderNotFoundError: 供应商类型未注册
        """
        factory = self._factories.get(config.provider_type)
        if not factory:
            raise ProviderNotFoundError(config.provider_type)

        metadata = self._metadata.get(config.provider_type)
        base_url = config.base_url or (metadata.default_base_url if metadata else "")
        model = config.model or (metadata.default_model if metadata else "")

        return factory(
            api_key=config.api_key,
            base_url=base_url,
            model=model,
            timeout=config.timeout,
            extra_body=config.extra_body or None,
        )

    def get_metadata(self, provider_type: str) -> ProviderMetadata | None:
        """获取供应商元信息。"""
        return self._metadata.get(provider_type)

    def list_providers(self) -> list[ProviderMetadata]:
        """列出所有已注册供应商。"""
        return list(self._metadata.values())

    def has_provider(self, provider_type: str) -> bool:
        """检查供应商类型是否已注册。"""
        return provider_type in self._factories

    def _register_builtin_providers(self) -> None:
        """注册内置供应商。"""
        # 延迟导入避免循环依赖
        from core.llm.providers.aiping_rerank import AIPingRerankProvider
        from core.llm.providers.anthropic import AnthropicProvider
        from core.llm.providers.chat import ChatProvider
        from core.llm.providers.embedding import EmbeddingProvider
        from core.llm.providers.rerank import RerankProvider

        # OpenAI 兼容 Chat Provider
        self.register(
            "openai",
            lambda api_key, base_url, model, timeout, extra_body=None: ChatProvider(
                api_key=api_key,
                base_url=base_url or "https://api.openai.com/v1",
                model=model or "gpt-4o",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="openai",
                display_name="OpenAI",
                capabilities=frozenset(
                    {
                        ProviderCapability.CHAT,
                        ProviderCapability.EMBEDDING,
                        ProviderCapability.FUNCTION_CALLING,
                        ProviderCapability.STREAMING,
                        ProviderCapability.VISION,
                    }
                ),
                default_base_url="https://api.openai.com/v1",
                default_model="gpt-4o",
            ),
        )

        # Anthropic Claude
        self.register(
            "anthropic",
            lambda api_key, base_url, model, timeout, extra_body=None: AnthropicProvider(
                api_key=api_key,
                base_url=base_url,
                model=model or "claude-sonnet-4-20250514",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="anthropic",
                display_name="Anthropic Claude",
                capabilities=frozenset(
                    {
                        ProviderCapability.CHAT,
                        ProviderCapability.VISION,
                        ProviderCapability.STREAMING,
                    }
                ),
                default_base_url="",
                default_model="claude-sonnet-4-20250514",
            ),
        )

        # Embedding Provider (OpenAI 兼容)
        self.register(
            "embedding",
            lambda api_key, base_url, model, timeout, extra_body=None: EmbeddingProvider(
                api_key=api_key,
                base_url=base_url or "https://api.openai.com/v1",
                model=model or "text-embedding-3-large",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="embedding",
                display_name="OpenAI Embeddings",
                capabilities=frozenset({ProviderCapability.EMBEDDING}),
                default_base_url="https://api.openai.com/v1",
                default_model="text-embedding-3-large",
            ),
        )

        # Rerank Provider
        self.register(
            "rerank",
            lambda api_key, base_url, model, timeout, extra_body=None: RerankProvider(
                api_key=api_key,
                base_url=base_url,
                model=model or "jina-reranker-v2",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="rerank",
                display_name="Rerank Provider",
                capabilities=frozenset({ProviderCapability.RERANK}),
                default_base_url="",
                default_model="jina-reranker-v2",
            ),
        )

        # Ollama (本地模型) - 使用 OpenAI 兼容接口
        self.register(
            "ollama",
            lambda api_key, base_url, model, timeout, extra_body=None: ChatProvider(
                api_key=api_key or "ollama",
                base_url=base_url or "http://localhost:11434/v1",
                model=model or "qwen3.5:9b",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="ollama",
                display_name="Ollama (Local)",
                capabilities=frozenset(
                    {
                        ProviderCapability.CHAT,
                        ProviderCapability.EMBEDDING,
                    }
                ),
                default_base_url="http://localhost:11434/v1",
                default_model="qwen3.5:9b",
                requires_api_key=False,
            ),
        )

        # aiping AI Rerank (Custom REST API)
        self.register(
            "aiping_rerank",
            lambda api_key, base_url, model, timeout, extra_body=None: AIPingRerankProvider(
                api_key=api_key,
                base_url=base_url or "https://www.aiping.cn/api/v1",
                model=model or "Qwen3-Reranker-0.6B",
                timeout=timeout,
                extra_body=extra_body,
            ),
            ProviderMetadata(
                name="aiping_rerank",
                display_name="aiping Rerank",
                capabilities=frozenset({ProviderCapability.RERANK}),
                default_base_url="https://www.aiping.cn/api/v1",
                default_model="Qwen3-Reranker-0.6B",
            ),
        )
