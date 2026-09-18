# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""JSON parsing utilities using json_repair."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from json_repair import repair_json
from pydantic import BaseModel, ValidationError

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

    # Pre-check: whether content is clearly not JSON (no structured markers)
    stripped = content.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        # 尝试从markdown提取
        extracted = extract_json_from_markdown(content)
        if extracted != stripped:
            # Found JSON in markdown, use extracted content
            stripped = extracted
        else:
            # 尝试从文本中提取 JSON 对象/数组（LLM 有时在 JSON 前加说明文字）
            json_extracted = extract_json_from_text(content)
            if json_extracted:
                stripped = json_extracted
            else:
                # 所有提取策略均失败：内容不含 JSON 标记。
                # 显式报错而非将非 JSON 文本喂给 repair_json（规则12 失败必须显性化）。
                model_name = f" for {model.__name__}" if model else ""
                raise ValueError(
                    f"LLM output is not JSON format. "
                    f"Content starts with: '{stripped[:50]}...' "
                    f"Expected JSON object or array{model_name}"
                )

    try:
        repaired = repair_json(stripped)

        # 如果返回字符串,需要再次解析
        if isinstance(repaired, str):
            repaired = json.loads(repaired)

        # repair_json can return None for unrecoverable input — surface a
        # clear error instead of an opaque model_validate(None) TypeError.
        if repaired is None:
            raise ValueError("json_repair could not recover a JSON structure from the content")

        if model:
            return model.model_validate(repaired)

        return repaired

    except ValidationError:
        # 模型/schema 不匹配属于不可重试错误：保留原始类型（ValidationError
        # 继承自 ValueError，不破坏既有 except ValueError 调用方），
        # 以便上游区分「JSON 解析失败（可能可重试）」与「字段校验失败」。
        raise
    except Exception as e:
        raise ValueError(f"Failed to parse LLM JSON response ({type(e).__name__}): {e}") from e


def extract_json_from_markdown(content: str) -> str:
    """从markdown代码块中提取JSON.

    Args:
        content: 可能包含markdown代码块的内容

    Returns:
        提取出的JSON字符串

    """
    import re

    # Prefer an explicit ```json fenced block: when the LLM emits multiple
    # blocks (e.g. a ```python example followed by the JSON payload), the
    # first arbitrary block would otherwise win and feed non-JSON content
    # downstream.
    json_match = re.search(r"```json\s*\n?(.*?)\n?```", content, re.DOTALL | re.IGNORECASE)
    if json_match:
        return json_match.group(1).strip()

    # Fall back to the first fenced block of any language
    pattern = r"```\s*\n?(.*?)\n?```"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        return match.group(1).strip()

    return content.strip()


def extract_json_from_text(content: str) -> str:
    """从任意文本中提取 JSON 对象或数组.

    处理 LLM 在 JSON 前后添加说明文字的情况，例如::

        `score`: 0.85 is fine....
        {"score": 0.85, "sentiment": "neutral", ...}

    策略：取最先出现的 ``{`` 或 ``[`` 作为起点，用括号配对找到完整的
    JSON 块。使用括号配对而非纯正则，避免嵌套 JSON 被截断，且正确
    处理字符串内的括号。

    局限性：状态机只跟踪双引号 ``"``，这是严格 JSON 的假设。若 LLM 输出
    中出现单引号包裹的字符串（``'foo'``）、未转义的裸换行/制表符等非
    严格 JSON 形态，``in_string`` 状态可能失配，导致返回空字符串。
    此时调用方（``parse_llm_json``）会退回到 ``json_repair`` 全量修复路径。

    Args:
        content: 可能包含 JSON 的任意文本

    Returns:
        提取出的 JSON 字符串，未找到则返回空字符串

    """
    brace_pos = content.find("{")
    bracket_pos = content.find("[")

    # 取最先出现的开括号
    if brace_pos == -1 and bracket_pos == -1:
        return ""
    if brace_pos == -1:
        start, open_char, close_char = bracket_pos, "[", "]"
    elif bracket_pos == -1:
        start, open_char, close_char = brace_pos, "{", "}"
    else:
        if brace_pos < bracket_pos:
            start, open_char, close_char = brace_pos, "{", "}"
        else:
            start, open_char, close_char = bracket_pos, "[", "]"

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(content)):
        ch = content[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    return ""


def _scan_balanced_end(text: str, start: int) -> int:
    """Scan ``text`` from ``start`` (an opening ``{``) to the matching close.

    Tracks double-quote string state so braces inside JSON string values do
    not corrupt the depth count.

    Returns:
        Index of the matching closing ``}`` (inclusive), or -1 if unbalanced.
    """
    depth = 0
    in_string = False
    escaped = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def extract_last_json_object(content: str, max_candidates: int = 128) -> dict[str, Any] | None:
    """Extract the last valid JSON object from text that may contain
    thinking/reasoning.

    LLMs with think mode may return reasoning text before (and JSON payloads
    after) prose, so candidates are tried from the last opening brace
    backwards. Each failed candidate scans to its matching close only, and
    the candidate list is capped to bound pathological brace-heavy inputs.

    Args:
        content: Raw LLM response text.
        max_candidates: Maximum opening-brace candidates to try.

    Returns:
        Parsed dict if a balanced JSON object is found, None otherwise.
    """
    starts = [i for i, ch in enumerate(content) if ch == "{"][-max_candidates:]
    for i in reversed(starts):
        end = _scan_balanced_end(content, i)
        if end == -1:
            continue
        try:
            return json.loads(content[i : end + 1])
        except (json.JSONDecodeError, TypeError):
            continue
    return None
