# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for core.llm.utils.json_parser."""

import pytest
from pydantic import BaseModel

from core.llm.utils.json_parser import (
    OutputParserException,
    extract_json_from_markdown,
    extract_json_from_text,
    parse_llm_json,
)


class ScoreModel(BaseModel):
    """Test model for parse_llm_json structured output."""

    score: float
    sentiment: str


class TestExtractJsonFromText:
    """Tests for extract_json_from_text — extract JSON from arbitrary text."""

    def test_plain_json_object(self):
        """JSON object without surrounding text."""
        content = '{"score": 0.85, "sentiment": "neutral"}'
        result = extract_json_from_text(content)
        assert result == content

    def test_json_with_prefix_text(self):
        """LLM adds explanatory text before JSON."""
        content = '`score`: 0.85 is fine....\n{"score": 0.85, "sentiment": "neutral"}'
        result = extract_json_from_text(content)
        assert '"score"' in result
        assert '"sentiment"' in result

    def test_json_with_suffix_text(self):
        """LLM adds text after JSON."""
        content = '{"score": 0.85, "sentiment": "neutral"}\n以上是分析结果。'
        result = extract_json_from_text(content)
        assert result.startswith("{")
        assert result.endswith("}")

    def test_nested_json_object(self):
        """Nested JSON objects should be fully extracted."""
        content = '说明文字\n{"outer": {"inner": "value"}, "num": 42}'
        result = extract_json_from_text(content)
        assert '"inner"' in result
        assert "42" in result

    def test_json_array(self):
        """JSON array extraction."""
        content = '结果如下：\n[{"a": 1}, {"b": 2}]'
        result = extract_json_from_text(content)
        assert result.startswith("[")
        assert result.endswith("]")

    def test_braces_inside_strings(self):
        """Braces inside string values should not break extraction."""
        content = 'text {"code": "function() { return 0; }"}'
        result = extract_json_from_text(content)
        assert '"code"' in result
        assert "return 0" in result

    def test_no_json_returns_empty(self):
        """No JSON markers returns empty string."""
        result = extract_json_from_text("just plain text without json")
        assert result == ""

    def test_empty_content(self):
        """Empty content returns empty string."""
        assert extract_json_from_text("") == ""


class TestParseLlmJson:
    """Tests for parse_llm_json — full parsing pipeline."""

    def test_plain_json_dict(self):
        """Plain JSON dict without model."""
        result = parse_llm_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_plain_json_with_model(self):
        """Plain JSON with model validation."""
        result = parse_llm_json('{"score": 0.85, "sentiment": "neutral"}', model=ScoreModel)
        assert result.score == 0.85
        assert result.sentiment == "neutral"

    def test_markdown_wrapped_json(self):
        """JSON in markdown code block."""
        content = '```json\n{"score": 0.9, "sentiment": "positive"}\n```'
        result = parse_llm_json(content, model=ScoreModel)
        assert result.score == 0.9

    def test_json_with_prefix_text_parsed(self):
        """LLM adds text before JSON — should extract and parse."""
        content = '`score`: 0.85 is fine....\n{"score": 0.85, "sentiment": "neutral"}'
        result = parse_llm_json(content, model=ScoreModel)
        assert result.score == 0.85
        assert result.sentiment == "neutral"

    def test_empty_content_without_model(self):
        """Empty content without model returns empty dict."""
        assert parse_llm_json("") == {}

    def test_empty_content_with_model_raises(self):
        """Empty content with model raises ValueError."""
        with pytest.raises(ValueError, match="Empty content"):
            parse_llm_json("", model=ScoreModel)

    def test_no_json_with_model_raises(self):
        """Content with no JSON and model raises ValueError."""
        with pytest.raises(ValueError, match="not JSON format"):
            parse_llm_json("just plain text", model=ScoreModel)

    def test_no_json_without_model_raises(self):
        """Content with no JSON and no model also raises ValueError (规则12)."""
        with pytest.raises(ValueError, match="not JSON format"):
            parse_llm_json("just plain text without any json")
