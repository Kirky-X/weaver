# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Contributors
"""Unit tests for the analyze + narrative_schema merge (LLM 调用优化方案 A/B).

Covers (docs/LLM调用优化方案.md §9.1):
1. AnalyzeNarrativeOutput parses a full 18-field JSON; to_narrative_payload
   splits correctly with field constraints mirroring NarrativeSchemaOutput.
2. AnalyzeNode merged mode: single ANALYZE_NARRATIVE call, narrative payload
   staged into state, prompt version recorded.
3. AnalyzeNode flag off: behavior identical to the original path (ANALYZE +
   AnalyzeOutput, no staged payload) — regression guarantee.
4. AnalyzeNode merged failure: defaults applied AND degraded_fields contains
   both "narrative" and "schema" (failure-correlation observability).
5. NarrativeSchemaExtractorNode merged mode: consumes staged payload, issues
   no LLM call, persists both writes.
6. NarrativeSchemaExtractorNode fallback: standalone call payload no longer
   carries "entities" (方案 B — prompt never consumed it; it polluted the
   cache key and input tokens).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import (
    AnalyzeNarrativeOutput,
    AnalyzeOutput,
    NarrativeSchemaOutput,
)
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.analyze import AnalyzeNode
from modules.processing.nodes.extraction.narrative_schema_extractor import (
    NarrativeSchemaExtractorNode,
)
from modules.processing.pipeline.state import PipelineState

_VALID_PATTERN = (
    '{"type":"object","properties":{"company":{"type":"string"},"amount":{"type":"string"}}}'
)

_FULL_MERGED_JSON = {
    "summary": "央行宣布降准0.5个百分点。",
    "event_time": "2025-03-18T09:30:00",
    "subjects": ["中国人民银行"],
    "key_data": ["降准0.5个百分点"],
    "impact": "降低实体经济融资成本",
    "has_data": True,
    "sentiment": "positive",
    "sentiment_score": 0.72,
    "primary_emotion": "乐观",
    "emotion_targets": ["央行"],
    "score": 0.82,
    "source_bias": "官方",
    "frame": "政策监管",
    "tone": "客观",
    "emphasis": "货币政策调整",
    "event_type": "政策发布",
    "pattern": _VALID_PATTERN,
    "confidence": 0.9,
}


def _narrative_output() -> NarrativeSchemaOutput:
    return NarrativeSchemaOutput(
        source_bias="中立",
        frame="经济影响",
        tone="客观",
        emphasis="事件概述",
        event_type="融资",
        pattern=_VALID_PATTERN,
        confidence=0.8,
    )


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/tech-news",
        title="OpenAI and Microsoft Announce Partnership",
        body=(
            "OpenAI and Microsoft have announced a major partnership deal. "
            "The agreement involves GPT-4 integration into Azure services."
        ),
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    loader = MagicMock()
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


def _make_state(raw: RawArticle) -> PipelineState:
    state = PipelineState(raw=raw)
    state["cleaned"] = {"title": raw.title, "body": raw.body}
    return state


# ── 1. 合并输出模型 ──────────────────────────────────────────────


class TestAnalyzeNarrativeOutputModel:
    def test_parses_full_merged_json(self) -> None:
        model = AnalyzeNarrativeOutput.model_validate(_FULL_MERGED_JSON)
        assert model.summary.startswith("央行")
        assert model.event_type == "政策发布"
        assert 0.0 <= model.confidence <= 1.0

    def test_to_narrative_payload_splits_correctly(self) -> None:
        model = AnalyzeNarrativeOutput.model_validate(_FULL_MERGED_JSON)
        payload = model.to_narrative_payload()
        assert isinstance(payload, NarrativeSchemaOutput)
        assert payload.event_type == model.event_type
        assert payload.pattern == model.pattern
        assert payload.frame == model.frame
        assert payload.tone == model.tone
        assert payload.emphasis == model.emphasis
        assert payload.source_bias == model.source_bias
        assert payload.confidence == model.confidence

    def test_narrative_constraints_mirror_schema_output(self) -> None:
        """narrative 侧字段约束必须与 NarrativeSchemaOutput 逐字一致（防注入防线）。"""
        merged_fields = AnalyzeNarrativeOutput.model_fields
        base_fields = NarrativeSchemaOutput.model_fields
        for name in base_fields:
            assert name in merged_fields, f"missing field: {name}"
            # metadata 对象无结构相等性，用 repr 逐字节比较约束内容
            assert repr(merged_fields[name].metadata) == repr(base_fields[name].metadata), name
            assert merged_fields[name].annotation == base_fields[name].annotation, name

    def test_invalid_pattern_rejected(self) -> None:
        bad = dict(_FULL_MERGED_JSON, pattern="not-json")
        with pytest.raises(ValueError):
            AnalyzeNarrativeOutput.model_validate(bad)

    @pytest.mark.parametrize("model_cls", [NarrativeSchemaOutput, AnalyzeNarrativeOutput])
    def test_pattern_type_must_be_object(self, model_cls) -> None:
        """pattern 校验必须拒绝非 object 型伪 schema（写入 SchemaNode 后
        会被 SchemaDrivenStructuredOutput 当作 response_format 消费）。"""
        kwargs = {
            "source_bias": "中立",
            "frame": "经济影响",
            "tone": "客观",
            "emphasis": "事件概述",
            "event_type": "融资",
            "confidence": 0.8,
        }
        with pytest.raises(ValueError):
            model_cls(**kwargs, pattern='{"type":"string"}')
        with pytest.raises(ValueError):
            model_cls(**kwargs, pattern='{"type":"object"}')


# ── 2/3/4. AnalyzeNode 合并 / 开关回归 / 失败降级 ────────────────


class TestAnalyzeNodeMerge:
    async def test_merged_mode_single_call_and_payload_staged(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        merged = AnalyzeNarrativeOutput.model_validate(_FULL_MERGED_JSON)
        mock_llm.call_at.return_value = merged
        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader, merge_narrative=True)
        state = _make_state(sample_raw)

        result = await node.execute(state)

        mock_llm.call_at.assert_awaited_once()
        assert mock_llm.call_at.await_args.args[0] is CallPoint.ANALYZE_NARRATIVE
        assert mock_llm.call_at.await_args.kwargs["output_model"] is AnalyzeNarrativeOutput
        assert result["summary_info"]["summary"].startswith("央行")
        assert result["score"] == 0.82
        staged = state.get("_narrative_schema_payload")
        assert isinstance(staged, NarrativeSchemaOutput)
        assert staged.event_type == "政策发布"
        assert state["prompt_versions"]["analyze_narrative"] == "1.0.0"

    async def test_flag_off_matches_original_path(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        analyze_out = AnalyzeOutput(
            summary="s",
            score=0.5,
            sentiment="neutral",
            sentiment_score=0.5,
            primary_emotion="客观",
        )
        mock_llm.call_at.return_value = analyze_out
        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader, merge_narrative=False)
        state = _make_state(sample_raw)

        await node.execute(state)

        mock_llm.call_at.assert_awaited_once()
        assert mock_llm.call_at.await_args.args[0] is CallPoint.ANALYZE
        assert mock_llm.call_at.await_args.kwargs["output_model"] is AnalyzeOutput
        assert "_narrative_schema_payload" not in state
        assert state["prompt_versions"]["analyze"] == "1.0.0"
        assert "analyze_narrative" not in state.get("prompt_versions", {})

    async def test_merged_failure_degrades_both(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        mock_llm.call_at.side_effect = CircuitOpenError("agnes")
        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader, merge_narrative=True)
        state = _make_state(sample_raw)

        result = await node.execute(state)

        assert result["score"] == 0.5  # defaults applied
        assert set(result.get("degraded_fields", [])) >= {"narrative", "schema"}
        assert "_narrative_schema_payload" not in state


# ── 5/6. NarrativeSchemaExtractorNode 合并消费 / 方案 B ──────────


class TestNarrativeSchemaExtractorMergeAndFallback:
    async def test_merged_mode_consumes_payload_without_llm(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        graph_writer = AsyncMock()
        graph_writer.merge_narrative.return_value = "narrative-1"
        graph_writer.merge_schema.return_value = "schema-融资"
        node = NarrativeSchemaExtractorNode(mock_llm, mock_budget, mock_prompt_loader, graph_writer)
        state = _make_state(sample_raw)
        state["article_id"] = "a1"
        state["_narrative_schema_payload"] = _narrative_output()

        result = await node.execute(state)

        mock_llm.call_at.assert_not_awaited()
        assert result["narrative"]["narrative_id"] == "narrative-1"
        assert result["schema"]["schema_id"] == "schema-融资"
        assert "_narrative_schema_payload" not in result
        assert "narrative_schema" not in result.get("prompt_versions", {})

    async def test_fallback_payload_has_no_entities(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        graph_writer = AsyncMock()
        graph_writer.merge_narrative.return_value = "n1"
        graph_writer.merge_schema.return_value = "s1"
        mock_llm.call_at.return_value = _narrative_output()
        node = NarrativeSchemaExtractorNode(mock_llm, mock_budget, mock_prompt_loader, graph_writer)
        state = _make_state(sample_raw)
        state["article_id"] = "a1"
        state["entities"] = [{"name": "OpenAI", "type": "ORG"}]

        await node.execute(state)

        mock_llm.call_at.assert_awaited_once()
        assert mock_llm.call_at.await_args.args[0] is CallPoint.NARRATIVE_SCHEMA
        payload = mock_llm.call_at.await_args.args[1]
        assert "entities" not in payload

    async def test_fallback_llm_failure_degrades_both(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        mock_llm.call_at.side_effect = CircuitOpenError("agnes")
        node = NarrativeSchemaExtractorNode(mock_llm, mock_budget, mock_prompt_loader, AsyncMock())
        state = _make_state(sample_raw)

        result = await node.execute(state)

        assert set(result.get("degraded_fields", [])) >= {"narrative", "schema"}
        assert result["prompt_versions"]["narrative_schema"] == "1.0.0"

    async def test_merge_mode_missing_payload_skips_llm(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ) -> None:
        """合并开启但 payload 缺失（analyze 已失败并标记 degraded）→
        本节点必须跳过自有调用：拆分重试会抵消合并收益，且与 analyze
        侧的 degraded 标记语义矛盾（假阳性）。"""
        node = NarrativeSchemaExtractorNode(
            mock_llm,
            mock_budget,
            mock_prompt_loader,
            AsyncMock(),
            merge_narrative=True,
        )
        state = _make_state(sample_raw)
        state["article_id"] = "a1"
        state.setdefault("degraded_fields", []).extend(["narrative", "schema"])

        result = await node.execute(state)

        mock_llm.call_at.assert_not_awaited()
        assert "narrative" not in result
        assert "schema" not in result
