# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM label parsing for tag-based provider selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from core.llm.types import LLMType


class InvalidLabelError(ValueError):
    """Raised when a label string cannot be parsed."""

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(
            f"Invalid label format: '{label}'. "
            f"Expected format: 'type.provider.model' "
            f"(e.g., 'chat.aiping.GLM-4-9B-0414')"
        )


@dataclass(frozen=True, slots=True)
class Label:
    """LLM 调用标签，用于标识调用类型、供应商和模型。

    格式: {type}.{provider}.{model}
    示例: chat.aiping.GLM-4-9B-0414

    Attributes:
        llm_type: LLM 类型 (chat/embedding/rerank)
        provider: 供应商名称
        model: 模型名称
    """

    llm_type: LLMType
    provider: str
    model: str

    @classmethod
    def parse(cls, label: str) -> Self:
        """解析标签字符串。

        Args:
            label: 标签字符串，格式为 'type.provider.model'

        Returns:
            解析后的 Label 对象

        Raises:
            InvalidLabelError: 标签格式无效
        """
        parts = label.split(".", 2)
        if len(parts) != 3:
            raise InvalidLabelError(label)

        type_str, provider, model = parts

        try:
            llm_type = LLMType(type_str)
        except ValueError:
            raise InvalidLabelError(label) from None

        if not provider or not model:
            raise InvalidLabelError(label)

        return cls(llm_type=llm_type, provider=provider, model=model)

    def __str__(self) -> str:
        return f"{self.llm_type.value}.{self.provider}.{self.model}"
