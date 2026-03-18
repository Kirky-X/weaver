# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Structured output validation and Pydantic output models for LLM responses."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class OutputParserException(Exception):
    """Raised when LLM output cannot be parsed into the expected model."""

    pass


def parse_llm_json(raw: str, model_cls: type[T]) -> T:
    """Parse raw LLM output into a Pydantic model.

    Handles common LLM quirks:
    - Strips Markdown code block wrappers (```json ... ```)
    - Handles trailing content after valid JSON
    - Handles plain float output for QualityScorerOutput
    - Handles Claude extended thinking format (dict with 'thinking' key)
    - Validates against the Pydantic model schema

    Args:
        raw: Raw string output from the LLM.
        model_cls: Target Pydantic model class.

    Returns:
        Validated Pydantic model instance.

    Raises:
        OutputParserException: If parsing or validation fails.
    """
    import ast

    if isinstance(raw, list):
        raw = "".join(block.text if hasattr(block, "text") else str(block) for block in raw)

    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # Handle Claude extended thinking format: {'thinking': '...', 'signature': '...'}
    # The actual JSON output should be after the thinking block
    # Simple approach: find the last complete JSON object
    if clean.startswith("{'") or clean.startswith('{"'):
        # Find the last complete JSON object by finding the last } and matching {
        last_brace = clean.rfind("}")
        if last_brace != -1:
            # Work backwards to find the matching {
            brace_count = 0
            in_string = False
            escape_next = False
            string_char = None

            for i in range(last_brace, -1, -1):
                char = clean[i]

                # Handle escape sequences
                if escape_next:
                    escape_next = False
                    continue
                if i > 0 and clean[i - 1] == "\\":
                    escape_next = True
                    continue

                # Track string boundaries
                if char in ('"', "'") and not in_string:
                    in_string = True
                    string_char = char
                elif in_string and char == string_char:
                    in_string = False
                    string_char = None
                elif not in_string:
                    if char == "}":
                        brace_count += 1
                    elif char == "{":
                        brace_count -= 1
                        if brace_count == 0:
                            # Found the matching opening brace
                            clean = clean[i : last_brace + 1]
                            break

    # Handle plain float output for QualityScorerOutput
    if model_cls.__name__ == "QualityScorerOutput":
        float_match = re.search(r"^([0-9]*\.?[0-9]+)$", clean)
        if float_match:
            try:
                score = float(float_match.group(1))
                return model_cls(score=score)  # type: ignore
            except ValueError:
                pass

    # Try to find valid JSON within the output
    # Handle cases where model outputs extra text after JSON
    json_match = re.search(r"\{[\s\S]*\}", clean)
    if json_match:
        clean = json_match.group(0)

    try:
        data = json.loads(clean)
        return model_cls.model_validate(data)
    except json.JSONDecodeError:
        # Try ast.literal_eval for Python dict format (single quotes)
        try:
            data = ast.literal_eval(clean)
            return model_cls.model_validate(data)
        except Exception:
            pass
    except Exception as e:
        raise OutputParserException(f"验证失败: {e!s}\n原始内容: {raw[:200]}")

    raise OutputParserException(f"解析失败: 无法解析为有效的 JSON\n原始内容: {raw[:200]}")


# ── Output Models ────────────────────────────────────────────


class ClassifierOutput(BaseModel):
    """Output model for the classifier node."""

    is_news: bool
    confidence: float = Field(ge=0, le=1)


class CleanerContent(BaseModel):
    """Content sub-model for cleaner output."""

    title: str
    subtitle: str | None = None
    summary: str | None = None
    body: str


class CleanerEntity(BaseModel):
    """Entity sub-model for cleaner output."""

    name: str
    type: str
    description: str


class CleanerOutput(BaseModel):
    """Output model for the cleaner node."""

    publish_time: str | None = None
    author: str | None = None
    content: CleanerContent
    tags: list[str] = Field(default_factory=list)
    entities: list[CleanerEntity] = Field(default_factory=list)


class CategorizerOutput(BaseModel):
    """Output model for the categorizer node."""

    category: str
    language: str
    region: str


class AnalyzeOutput(BaseModel):
    """Output model for the analyze node (summary + score + sentiment)."""

    summary: str
    event_time: str | None = None
    subjects: list[str] = Field(default_factory=list)
    key_data: list[str] = Field(default_factory=list)
    impact: str = ""
    has_data: bool = False
    sentiment: str = "neutral"
    sentiment_score: float = Field(ge=-1, le=1, default=0.5)
    primary_emotion: str = "客观"
    emotion_targets: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=1, default=0.5)


class CredibilityOutput(BaseModel):
    """Output model for the credibility checker node."""

    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)


class QualityScorerOutput(BaseModel):
    """Output model for the quality scorer node."""

    score: float = Field(ge=0, le=1, default=0.5)


class EntityExtractorOutput(BaseModel):
    """Output model for the entity extractor node."""

    entities: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


class EntityResolverOutput(BaseModel):
    """Output model for the entity resolver."""

    is_same: bool = False
    matched_id: str | None = None
    confidence: float = Field(ge=0, le=1, default=0.0)
    reason: str = ""


class MergerOutput(BaseModel):
    """Output model for the merger node."""

    merged_title: str
    merged_body: str
