# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""回归：parse_llm_json 的 ValidationError 分支引用未导入的异常类。

该文件曾使用 ValidationError 却未 import，except 匹配阶段抛 NameError
并替换原始校验错误——analyze 节点因此每次都落入默认值分支。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from core.llm.utils.json_parser import parse_llm_json


class _Strict(BaseModel):
    name: str
    count: int


class TestParseLlmJsonValidationError:
    def test_schema_mismatch_raises_validation_error_not_name_error(self) -> None:
        """字段校验失败必须抛 ValidationError（而非 NameError）。"""
        with pytest.raises(ValidationError):
            parse_llm_json('{"name": "x"}', model=_Strict)  # 缺 count

    def test_valid_json_passes_schema(self) -> None:
        result = parse_llm_json('{"name": "x", "count": 3}', model=_Strict)
        assert result.name == "x"
        assert result.count == 3

    def test_broken_json_raises_value_error(self) -> None:
        """不可修复的非 JSON 内容仍按 ValueError 抛出（可区分语义）。"""
        with pytest.raises(ValueError):
            parse_llm_json("not json at all {{{", model=_Strict)
