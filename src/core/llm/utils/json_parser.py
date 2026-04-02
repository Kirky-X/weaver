# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""JSON parsing utilities using json_repair."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from json_repair import repair_json
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class OutputParserException(Exception):
    """Raised when LLM output cannot be parsed into the expected model."""

    pass


def parse_llm_json(content: str, model: type[T] | None = None) -> T | dict[str, Any]:
    """使用json_repair解析LLM响应.

    json_repair 自动处理:
    - 修复转义字符
    - 移除markdown代码块标记
    - 修复截断的JSON
    - 处理尾随逗号
    - 修复缺失的引号

    Args:
        content: LLM返回的原始内容（可能包含markdown代码块、转义错误等）
        model: 可选的Pydantic模型，用于结构化输出

    Returns:
        解析后的字典或Pydantic模型实例

    Raises:
        ValueError: JSON解析失败且无法修复
    """
    if not content or not content.strip():
        if model:
            raise ValueError("Empty content cannot be parsed into model")
        return {}

    try:
        # json_repair 返回修复后的对象
        repaired = repair_json(content)

        # 如果返回字符串,需要再次解析
        if isinstance(repaired, str):
            repaired = json.loads(repaired)

        # 使用Pydantic模型验证
        if model:
            return model.model_validate(repaired)

        return repaired

    except Exception as e:
        raise ValueError(f"Failed to parse LLM JSON response: {e}") from e


def extract_json_from_markdown(content: str) -> str:
    """从markdown代码块中提取JSON.

    Args:
        content: 可能包含markdown代码块的内容

    Returns:
        提取出的JSON字符串
    """
    import re

    # 匹配 ```json ... ``` 或 ``` ... ```
    pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        return match.group(1).strip()

    return content.strip()
