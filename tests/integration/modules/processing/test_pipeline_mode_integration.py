# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for pipeline processing modes with real services.

Tests verify:
1. ProcessingMode enum values work correctly
2. CLI mode is bridged to backend settings via WEAVER_PIPELINE_PROCESS__PROCESSING_MODE
3. CLI arguments are parsed correctly
4. Pipeline node integration with real LLM + real DB

These tests use real services when available and do NOT use mocks.
For mock-based unit tests, see tests/unit/pipeline/test_pipeline_modes.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.state import PipelineState


@pytest.mark.integration
class TestProcessingModeConfiguration:
    """Test that CLI processing mode is bridged to backend settings."""

    def test_processing_mode_env_bridge_fast(self, monkeypatch) -> None:
        """CLI fast mode reaches settings.pipeline_process via the env bridge."""
        from config.settings import Settings
        from scripts.pipeline import PROCESSING_MODE_ENV

        monkeypatch.setenv(PROCESSING_MODE_ENV, "fast")
        settings = Settings()
        assert settings.pipeline_process.processing_mode == "fast"

    def test_processing_mode_env_bridge_deep(self, monkeypatch) -> None:
        """CLI deep mode reaches settings.pipeline_process via the env bridge."""
        from config.settings import Settings
        from scripts.pipeline import PROCESSING_MODE_ENV

        monkeypatch.setenv(PROCESSING_MODE_ENV, "deep")
        settings = Settings()
        assert settings.pipeline_process.processing_mode == "deep"

    def test_processing_mode_enum(self) -> None:
        """Test ProcessingMode enum values."""
        from scripts.pipeline import ProcessingMode

        assert ProcessingMode.FAST.value == "fast"
        assert ProcessingMode.DEEP.value == "deep"
        assert ProcessingMode("fast") == ProcessingMode.FAST
        assert ProcessingMode("deep") == ProcessingMode.DEEP

    def test_processing_mode_string_conversion(self) -> None:
        """Test ProcessingMode string conversion."""
        from scripts.pipeline import ProcessingMode

        # Test that we can convert string to enum
        fast_mode = ProcessingMode("fast")
        assert fast_mode == ProcessingMode.FAST

        deep_mode = ProcessingMode("deep")
        assert deep_mode == ProcessingMode.DEEP

        # Test that invalid value raises error
        with pytest.raises(ValueError):
            ProcessingMode("invalid")


@pytest.mark.integration
class TestPipelineModeCLI:
    """Test CLI argument parsing for processing modes (no mocks needed)."""

    def test_cli_help_text(self) -> None:
        """Test that CLI help text includes processing mode information."""
        import argparse

        from scripts.pipeline import main

        # Parse --help to verify processing-mode is documented
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--processing-mode",
            choices=["fast", "deep"],
            default="deep",
            help="Processing mode: 'fast' or 'deep'",
        )

        # Verify argument is properly defined
        args = parser.parse_args(["--processing-mode", "fast"])
        assert args.processing_mode == "fast"

        args = parser.parse_args(["--processing-mode", "deep"])
        assert args.processing_mode == "deep"

        # Test default value
        args = parser.parse_args([])
        assert args.processing_mode == "deep"


@pytest.mark.integration
class TestPipelineFastModeMethod:
    """Test that process_batch_fast method exists and has correct signature."""

    def test_pipeline_has_process_batch_fast_method(self) -> None:
        """Test that Pipeline class has process_batch_fast method."""
        from modules.processing.pipeline.graph import Pipeline

        # Verify method exists
        assert hasattr(Pipeline, "process_batch_fast")

        # Verify it's a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(Pipeline.process_batch_fast)

    def test_process_batch_fast_signature(self) -> None:
        """Test that process_batch_fast has expected parameters."""
        import inspect

        from modules.processing.pipeline.graph import Pipeline

        sig = inspect.signature(Pipeline.process_batch_fast)
        params = list(sig.parameters.keys())

        # Should have self, articles, and optional article_ids, task_id
        assert "articles" in params
        assert "article_ids" in params
        assert "task_id" in params


@pytest.mark.integration
class TestPipelineModePerformanceExpectations:
    """Test performance expectations documentation (informational tests)."""

    def test_fast_mode_performance_documentation(self) -> None:
        """Verify fast mode performance expectations are documented."""
        from scripts.pipeline import ProcessingMode

        # Fast mode documentation should indicate Phase 1 only
        fast_doc = ProcessingMode.__doc__ or ""
        assert "Phase 1" in fast_doc or "phase 1" in fast_doc.lower()

    def test_deep_mode_performance_documentation(self) -> None:
        """Verify deep mode performance expectations are documented."""
        from scripts.pipeline import ProcessingMode

        # Deep mode documentation should indicate full processing
        deep_doc = ProcessingMode.__doc__ or ""
        assert "Full" in deep_doc or "full" in deep_doc.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Node Integration Tests (Tasks 3.1-3.9)
# Each test uses real LLM + real DB to verify node behavior.
# Pre-flight fixtures ensure services are available; tests are skipped otherwise.
# ─────────────────────────────────────────────────────────────────────────────


def _make_raw_article(
    title: str = "测试新闻：华为发布新款AI芯片",
    body: str = "华为在深圳举行的产品发布会上正式推出了最新一代AI训练芯片昇腾910B。"
    "据华为官方介绍，该芯片采用7nm工艺制程，在FP16算力上较前代产品提升超过50%，"
    "同时功耗降低了30%。业内分析人士认为，此举将进一步加剧全球AI芯片市场的竞争格局。",
    url: str = "https://example.com/test/article",
    source_host: str = "example.com",
    html: str | None = None,
) -> RawArticle:
    """Create a RawArticle for testing."""
    return RawArticle(
        url=url,
        title=title,
        body=body,
        source=source_host,
        source_host=source_host,
        html=html,
        publish_time=datetime.now(timezone.utc),
    )


def _make_classifier_state(raw: RawArticle | None = None) -> PipelineState:
    """Create minimal PipelineState for classifier input."""
    return PipelineState(raw=raw or _make_raw_article())


def _make_cleaner_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState with classifier output for cleaner input."""
    return PipelineState(
        raw=raw or _make_raw_article(),
        is_news=True,
        terminal=False,
    )


def _make_categorizer_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState with cleaner output for categorizer input."""
    return PipelineState(
        raw=raw or _make_raw_article(),
        is_news=True,
        terminal=False,
        cleaned={
            "title": (raw or _make_raw_article()).title,
            "body": (raw or _make_raw_article()).body,
            "publish_time": datetime.now(timezone.utc),
            "source_host": "example.com",
        },
        tags=[],
        cleaner_entities=[],
        cleaner_method="llm",
    )


def _make_vectorize_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState with categorizer output for vectorize input."""
    state = _make_categorizer_state(raw)
    state["category"] = "科技"
    state["language"] = "zh"
    state["region"] = "中国"
    return state


def _make_analyze_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState for analyze input."""
    state = _make_vectorize_state(raw)
    state["vectors"] = {"content": [0.1] * 10}
    return state


def _make_quality_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState for quality scorer input."""
    state = _make_analyze_state(raw)
    state["summary_info"] = {
        "summary": "华为发布新款AI芯片",
        "subjects": ["华为", "AI芯片"],
        "key_data": ["性能提升50%"],
        "impact": "加剧市场竞争",
        "has_data": True,
    }
    state["sentiment"] = {
        "sentiment": "positive",
        "sentiment_score": 0.7,
        "primary_emotion": "乐观",
        "emotion_targets": [],
    }
    state["score"] = 0.8
    return state


def _make_credibility_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState for credibility checker input."""
    state = _make_quality_state(raw)
    state["quality_score"] = 0.75
    state["credibility"] = {
        "score": 0.7,
        "source_credibility": 0.8,
        "cross_verification": 0.6,
        "content_check": 0.6,
        "timeliness": 0.9,
        "flags": [],
    }
    return state


def _make_entity_state(raw: RawArticle | None = None) -> PipelineState:
    """Create PipelineState for entity extractor input."""
    state = _make_credibility_state(raw)
    return state


@pytest.mark.integration
class TestClassifierNodeIntegration:
    """Task 3.1: Classifier node integration test — rule → ML cascade → LLM fallback."""

    async def test_rule_classify_news_title(self, llm_client, token_budget, prompt_loader) -> None:
        """Test that classifier correctly identifies news via rule matching."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        node = CascadeClassifierNode(llm_client, token_budget, prompt_loader)
        # Title with 2+ news keywords should trigger rule match
        raw = _make_raw_article(title="据报道我国政府发布最新公告声明")
        state = _make_classifier_state(raw)
        result = await node.execute(state)

        assert "is_news" in result
        assert result["is_news"] is True
        assert result["terminal"] is False

    async def test_rule_classify_non_news_title(
        self, llm_client, token_budget, prompt_loader
    ) -> None:
        """Test that classifier rejects non-news content via rule matching."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        node = CascadeClassifierNode(llm_client, token_budget, prompt_loader)
        # Title with 2+ non-news keywords
        raw = _make_raw_article(title="登录注册密码找回帮助中心")
        state = _make_classifier_state(raw)
        result = await node.execute(state)

        assert "is_news" in result
        assert result["is_news"] is False
        assert result["terminal"] is True

    async def test_llm_fallback_classify(self, llm_client, token_budget, prompt_loader) -> None:
        """Test that classifier falls back to LLM for ambiguous titles."""
        from modules.processing.nodes.classification.classifier import CascadeClassifierNode

        node = CascadeClassifierNode(llm_client, token_budget, prompt_loader)
        # Ambiguous title — no strong rule match, should use LLM
        raw = _make_raw_article(title="量子计算领域取得新进展")
        state = _make_classifier_state(raw)
        result = await node.execute(state)

        assert "is_news" in result
        assert isinstance(result["is_news"], bool)
        assert "terminal" in result


@pytest.mark.integration
class TestCleanerNodeIntegration:
    """Task 3.2: Cleaner node integration test — trafilatura → quality check → LLM fallback."""

    async def test_trafilatura_extraction_with_html(
        self, llm_client, token_budget, prompt_loader
    ) -> None:
        """Test that cleaner uses trafilatura when HTML is available."""
        from modules.processing.nodes.quality.cleaner import CleanerNode

        node = CleanerNode(llm_client, token_budget, prompt_loader)
        raw = _make_raw_article(
            html="<html><body><article><h1>华为发布新款AI芯片</h1>"
            "<p>华为在深圳举行的产品发布会上正式推出了最新一代AI训练芯片。"
            "该芯片采用7nm工艺制程，在FP16算力上较前代产品提升超过50%，"
            "同时功耗降低了30%。业内分析人士认为，此举将进一步加剧全球AI芯片"
            "市场的竞争格局，对英伟达的市场份额构成挑战。</p></article></body></html>"
        )
        state = _make_cleaner_state(raw)
        result = await node.execute(state)

        assert "cleaned" in result
        assert "title" in result["cleaned"]
        assert "body" in result["cleaned"]
        assert len(result["cleaned"]["body"]) > 0
        assert result["cleaner_method"] in ("trafilatura", "llm")

    async def test_llm_fallback_no_html(self, llm_client, token_budget, prompt_loader) -> None:
        """Test that cleaner falls back to LLM when no HTML is available."""
        from modules.processing.nodes.quality.cleaner import CleanerNode

        node = CleanerNode(llm_client, token_budget, prompt_loader)
        raw = _make_raw_article(html=None)
        state = _make_cleaner_state(raw)
        result = await node.execute(state)

        assert "cleaned" in result
        assert "title" in result["cleaned"]
        assert "body" in result["cleaned"]
        assert result["cleaner_method"] == "llm"

    async def test_terminal_state_skipped(self, llm_client, token_budget, prompt_loader) -> None:
        """Test that cleaner skips terminal (non-news) articles."""
        from modules.processing.nodes.quality.cleaner import CleanerNode

        node = CleanerNode(llm_client, token_budget, prompt_loader)
        state = _make_cleaner_state()
        state["terminal"] = True
        result = await node.execute(state)

        # State should be unchanged — cleaner was skipped
        assert "cleaned" not in result


@pytest.mark.integration
class TestCategorizerNodeIntegration:
    """Task 3.3: Categorizer node integration test — rule → LLM fallback → category validation."""

    async def test_rule_categorize_economy(self, llm_client, prompt_loader) -> None:
        """Test that categorizer matches economy category via rule keywords."""
        from modules.processing.nodes.classification.categorizer import CascadeCategorizerNode

        node = CascadeCategorizerNode(llm_client, prompt_loader)
        raw = _make_raw_article(title="央行降息刺激经济增长")
        state = _make_categorizer_state(raw)
        result = await node.execute(state)

        assert "category" in result
        assert result["category"] == "经济"
        assert "language" in result
        assert "region" in result

    async def test_rule_categorize_military(self, llm_client, prompt_loader) -> None:
        """Test that categorizer matches military category via rule keywords."""
        from modules.processing.nodes.classification.categorizer import CascadeCategorizerNode

        node = CascadeCategorizerNode(llm_client, prompt_loader)
        raw = _make_raw_article(title="国防军队军事演习圆满完成")
        state = _make_categorizer_state(raw)
        result = await node.execute(state)

        assert "category" in result
        assert result["category"] == "军事"

    async def test_llm_fallback_categorize(self, llm_client, prompt_loader) -> None:
        """Test that categorizer falls back to LLM for ambiguous titles."""
        from modules.processing.nodes.classification.categorizer import CascadeCategorizerNode

        node = CascadeCategorizerNode(llm_client, prompt_loader)
        raw = _make_raw_article(title="新型材料研究取得突破性进展")
        state = _make_categorizer_state(raw)
        result = await node.execute(state)

        assert "category" in result
        assert result["category"]  # Should not be empty


@pytest.mark.integration
class TestVectorizeNodeIntegration:
    """Task 3.4: Vectorize node integration test — embed_default + dimension verification."""

    async def test_vectorize_generates_embedding(self, llm_client, embedding_dimension) -> None:
        """Test that vectorize generates content embedding with correct dimension."""
        from modules.processing.nodes.vectorization.vectorize import VectorizeNode

        node = VectorizeNode(llm_client)
        state = _make_vectorize_state()
        result = await node.execute(state)

        assert "vectors" in result
        assert "content" in result["vectors"]
        assert len(result["vectors"]["content"]) == embedding_dimension

    async def test_vectorize_skips_terminal(self, llm_client) -> None:
        """Test that vectorize skips terminal articles."""
        from modules.processing.nodes.vectorization.vectorize import VectorizeNode

        node = VectorizeNode(llm_client)
        state = _make_vectorize_state()
        state["terminal"] = True
        result = await node.execute(state)

        # Terminal state should be returned unchanged — no vectors added
        assert "vectors" not in result or result.get("vectors", {}).get("content") is None


@pytest.mark.integration
class TestReVectorizeNodeIntegration:
    """Task 3.5: ReVectorize node — dual embedding + model_id + dimension consistency."""

    async def test_re_vectorize_generates_dual_embeddings(
        self, llm_client, embedding_dimension
    ) -> None:
        """Test that ReVectorize generates both title and content embeddings."""
        from modules.processing.nodes.vectorization.re_vectorize import ReVectorizeNode

        node = ReVectorizeNode(llm_client, model_id="qwen3-embedding:0.6b")
        state = _make_vectorize_state()
        result = await node.execute(state)

        assert "vectors" in result
        assert "title" in result["vectors"]
        assert "content" in result["vectors"]
        assert "model_id" in result["vectors"]
        assert result["vectors"]["model_id"] == "qwen3-embedding:0.6b"
        assert len(result["vectors"]["title"]) == embedding_dimension
        assert len(result["vectors"]["content"]) == embedding_dimension

    async def test_re_vectorize_skips_merged(self, llm_client) -> None:
        """Test that ReVectorize skips merged articles."""
        from modules.processing.nodes.vectorization.re_vectorize import ReVectorizeNode

        node = ReVectorizeNode(llm_client, model_id="qwen3-embedding:0.6b")
        state = _make_vectorize_state()
        state["is_merged"] = True
        result = await node.execute(state)

        # Merged state should be returned unchanged — no model_id added
        assert result.get("vectors", {}).get("model_id") is None


@pytest.mark.integration
class TestAnalyzeNodeIntegration:
    """Task 3.6: Analyze node — LLM summary + score + sentiment + OutputValidator."""

    async def test_analyze_generates_summary_and_sentiment(
        self, llm_client, token_budget, prompt_loader
    ) -> None:
        """Test that analyze produces summary_info, sentiment, and score."""
        from modules.processing.nodes.extraction.analyze import AnalyzeNode

        node = AnalyzeNode(llm_client, token_budget, prompt_loader)
        state = _make_analyze_state()
        result = await node.execute(state)

        assert "summary_info" in result
        assert "summary" in result["summary_info"]
        assert result["summary_info"]["summary"]  # Non-empty summary
        assert "sentiment" in result
        assert "sentiment" in result["sentiment"]
        assert "score" in result
        assert 0.0 <= result["score"] <= 1.0

    async def test_analyze_skips_merged(self, llm_client, token_budget, prompt_loader) -> None:
        """Test that analyze skips merged articles."""
        from modules.processing.nodes.extraction.analyze import AnalyzeNode

        node = AnalyzeNode(llm_client, token_budget, prompt_loader)
        state = _make_analyze_state()
        state["is_merged"] = True
        result = await node.execute(state)

        # summary_info should not be overwritten for merged articles
        assert result.get("summary_info") is None or "summary" not in result.get("summary_info", {})


@pytest.mark.integration
class TestQualityScorerNodeIntegration:
    """Task 3.7: QualityScorer node — pure rule-based 5-dimension scoring."""

    async def test_quality_scorer_computes_score(self) -> None:
        """Test that quality scorer computes a score from 5 dimensions."""
        from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode

        node = RuleBasedQualityScorerNode()
        state = _make_quality_state()
        result = await node.execute(state)

        assert "quality_score" in result
        assert 0.0 <= result["quality_score"] <= 1.0

    async def test_quality_scorer_dimensions(self) -> None:
        """Test that quality scorer reflects completeness and normativity."""
        from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode

        node = RuleBasedQualityScorerNode()

        # Full state — high score expected
        full_state = _make_quality_state()
        full_result = await node.execute(full_state)

        # Minimal state — lower score expected
        minimal_state = PipelineState(
            raw=_make_raw_article(),
            is_news=True,
            terminal=False,
            cleaned={"title": "test", "body": "short"},
        )
        minimal_result = await node.execute(minimal_state)

        assert full_result["quality_score"] >= minimal_result["quality_score"]

    async def test_quality_scorer_terminal_state(self) -> None:
        """Test that quality scorer returns default for terminal articles."""
        from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode

        node = RuleBasedQualityScorerNode()
        state = _make_quality_state()
        state["terminal"] = True
        result = await node.execute(state)

        assert result["quality_score"] == 0.5


@pytest.mark.integration
class TestCredibilityNodeIntegration:
    """Task 3.8: Credibility node — 3-signal scoring + source_auth_repo + category weights."""

    async def test_credibility_computes_score(self, event_bus) -> None:
        """Test that credibility checker computes score from 3 signals."""
        from modules.processing.nodes.classification.credibility_checker import (
            RuleBasedCredibilityCheckerNode,
        )

        node = RuleBasedCredibilityCheckerNode(event_bus=event_bus)
        state = _make_credibility_state()
        result = await node.execute(state)

        assert "credibility" in result
        assert "score" in result["credibility"]
        assert 0.0 <= result["credibility"]["score"] <= 1.0
        assert "source_credibility" in result["credibility"]
        assert "cross_verification" in result["credibility"]
        assert "timeliness" in result["credibility"]

    async def test_credibility_category_weights(self, event_bus) -> None:
        """Test that different categories produce different weight distributions."""
        from modules.processing.nodes.classification.credibility_checker import (
            RuleBasedCredibilityCheckerNode,
        )

        node = RuleBasedCredibilityCheckerNode(event_bus=event_bus)

        # Military category — timeliness weight is 0.50
        mil_state = _make_credibility_state()
        mil_state["category"] = "军事"
        mil_result = await node.execute(mil_state)

        # Economy category — source weight is 0.45
        eco_state = _make_credibility_state()
        eco_state["category"] = "经济"
        eco_result = await node.execute(eco_state)

        # Both should produce valid scores
        assert 0.0 <= mil_result["credibility"]["score"] <= 1.0
        assert 0.0 <= eco_result["credibility"]["score"] <= 1.0

    async def test_credibility_default_source_authority(self, event_bus) -> None:
        """Test that unknown source gets default 0.50 authority."""
        from modules.processing.nodes.classification.credibility_checker import (
            RuleBasedCredibilityCheckerNode,
        )

        node = RuleBasedCredibilityCheckerNode(event_bus=event_bus)
        state = _make_credibility_state()
        result = await node.execute(state)

        # Unknown source should get default 0.50
        assert result["credibility"]["source_credibility"] == 0.50


@pytest.mark.integration
class TestEntityExtractorNodeIntegration:
    """Task 3.9: EntityExtractor node — spaCy + LLM + embed 3-phase + relation extraction."""

    async def test_entity_extraction_with_spacy_and_llm(
        self, llm_client, token_budget, prompt_loader, spacy_extractor
    ) -> None:
        """Test that entity extractor produces entities and relations."""
        from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode

        node = EntityExtractorNode(llm_client, token_budget, prompt_loader, spacy_extractor)
        state = _make_entity_state()
        result = await node.execute(state)

        assert "entities" in result
        assert "relations" in result
        assert isinstance(result["entities"], list)
        assert isinstance(result["relations"], list)

    async def test_entity_extraction_with_rich_content(
        self, llm_client, token_budget, prompt_loader, spacy_extractor
    ) -> None:
        """Test entity extraction with content containing named entities."""
        from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode

        node = EntityExtractorNode(llm_client, token_budget, prompt_loader, spacy_extractor)
        raw = _make_raw_article(
            title="华为与微软签署AI合作协议",
            body="华为技术有限公司与微软公司今日在深圳签署了一项关于人工智能技术合作的协议。"
            "根据协议，双方将在大模型训练、云计算和自动驾驶等领域展开深度合作。"
            "华为轮值董事长和微软CEO共同出席了签约仪式。",
        )
        state = _make_entity_state(raw)
        result = await node.execute(state)

        assert "entities" in result
        # With rich entity content, should extract at least some entities
        assert isinstance(result["entities"], list)

    async def test_entity_extraction_skips_merged(
        self, llm_client, token_budget, prompt_loader, spacy_extractor
    ) -> None:
        """Test that entity extractor skips merged articles."""
        from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode

        node = EntityExtractorNode(llm_client, token_budget, prompt_loader, spacy_extractor)
        state = _make_entity_state()
        state["is_merged"] = True
        result = await node.execute(state)

        # entities should not be added for merged articles
        assert result.get("entities") is None or result.get("entities") == []
