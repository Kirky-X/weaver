# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for GLiNER zero-shot entity extractor."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock gliner module before importing
mock_gliner = MagicMock()
sys.modules["gliner"] = mock_gliner

from modules.processing.nodes.extraction.gliner_extractor import (
    GLiNERConfig,
    GLiNERExtractor,
)


@pytest.fixture
def config() -> GLiNERConfig:
    """Default configuration for tests."""
    return GLiNERConfig()


@pytest.fixture
def extractor(config: GLiNERConfig) -> GLiNERExtractor:
    """GLiNERExtractor instance with mocked GLiNER."""
    with patch("gliner.GLiNER") as mock_gliner_class:
        mock_model = MagicMock()
        mock_gliner_class.from_pretrained.return_value = mock_model
        return GLiNERExtractor(config=config)


@pytest.fixture
def extractor_with_llm(config: GLiNERConfig) -> GLiNERExtractor:
    """GLiNERExtractor instance with mocked GLiNER and LLM."""
    with patch("gliner.GLiNER") as mock_gliner_class:
        mock_model = MagicMock()
        mock_gliner_class.from_pretrained.return_value = mock_model

        llm = AsyncMock()
        llm.call_at = AsyncMock(
            return_value={"entities": [{"text": "精炼实体", "type": "EVENT", "confidence": 0.8}]}
        )
        return GLiNERExtractor(config=config, llm_client=llm)


class TestGLiNERConfig:
    """Test GLiNERConfig defaults."""

    def test_default_config(self, config: GLiNERConfig) -> None:
        """Test that default config values are set correctly."""
        assert config.enabled is True
        assert config.model_name == "urchade/gliner_multi-v2.1"
        assert config.threshold == 0.5
        assert config.max_input_length == 4096
        assert "事件" in config.labels
        assert "数据指标" in config.labels
        assert "法规与政策" in config.labels
        assert "产品与技术" in config.labels


class TestGLiNERPrediction:
    """Test GLiNER zero-shot prediction."""

    @pytest.mark.asyncio
    async def test_predict_entities(self, extractor: GLiNERExtractor) -> None:
        """Test GLiNER entity prediction."""
        # Mock GLiNER to return entities
        extractor._model.predict_entities = MagicMock(
            return_value=[
                {"text": "某事件", "label": "事件", "score": 0.85},
                {"text": "38%", "label": "数据指标", "score": 0.75},
            ]
        )

        entities = await extractor.extract_entities("某公司季度营收同比增长38%")

        assert len(entities) >= 2
        assert any(e["text"] == "某事件" for e in entities)

    @pytest.mark.asyncio
    async def test_predict_entities_empty_text(self, extractor: GLiNERExtractor) -> None:
        """Test GLiNER prediction with empty text."""
        entities = await extractor.extract_entities("")
        assert entities == []

    @pytest.mark.asyncio
    async def test_predict_entities_exception(self, extractor: GLiNERExtractor) -> None:
        """Test GLiNER prediction exception handling."""
        # Mock GLiNER to raise exception
        extractor._model.predict_entities = MagicMock(side_effect=Exception("GLiNER error"))

        entities = await extractor.extract_entities("测试文本")

        # Should return empty list on error
        assert entities == []


class TestDualEngineMerge:
    """Test dual engine merge (spaCy + GLiNER)."""

    @pytest.mark.asyncio
    async def test_merge_entities_no_duplicates(self, extractor: GLiNERExtractor) -> None:
        """Test merging entities without duplicates."""
        spacy_entities = [
            {"text": "公司A", "type": "ORG", "confidence": 0.9},
            {"text": "张三", "type": "PERSON", "confidence": 0.85},
        ]
        gliner_entities = [
            {"text": "某事件", "type": "事件", "confidence": 0.8},
            {"text": "38%", "type": "数据指标", "confidence": 0.75},
        ]

        merged = extractor._merge_entities(spacy_entities, gliner_entities)

        assert len(merged) == 4
        assert any(e["text"] == "公司A" for e in merged)
        assert any(e["text"] == "某事件" for e in merged)

    @pytest.mark.asyncio
    async def test_merge_entities_with_duplicates(self, extractor: GLiNERExtractor) -> None:
        """Test merging entities with duplicates."""
        spacy_entities = [
            {"text": "公司A", "type": "ORG", "confidence": 0.9},
        ]
        gliner_entities = [
            {"text": "公司A", "type": "组织", "confidence": 0.85},
        ]

        merged = extractor._merge_entities(spacy_entities, gliner_entities)

        # Should keep the higher confidence one
        assert len(merged) == 1
        assert merged[0]["confidence"] == 0.9


class TestConfidenceGrading:
    """Test confidence grading (three-level pipeline)."""

    @pytest.mark.asyncio
    async def test_high_confidence_direct_store(self, extractor: GLiNERExtractor) -> None:
        """Test high confidence entities are stored directly."""
        entities = [
            {"text": "高置信实体", "type": "ORG", "confidence": 0.85},
        ]

        result = await extractor._apply_confidence_grading(entities, "测试文本")

        assert len(result) == 1
        assert result[0]["confidence"] >= 0.7
        assert result[0]["grading_action"] == "direct_store"

    @pytest.mark.asyncio
    async def test_medium_confidence_vector_link(self, extractor: GLiNERExtractor) -> None:
        """Test medium confidence entities go through vector linking."""
        entities = [
            {"text": "中置信实体", "type": "ORG", "confidence": 0.55},
        ]

        result = await extractor._apply_confidence_grading(entities, "测试文本")

        assert len(result) == 1
        assert result[0]["confidence"] >= 0.4
        assert result[0]["grading_action"] == "vector_link"

    @pytest.mark.asyncio
    async def test_low_confidence_llm_refine(self, extractor_with_llm: GLiNERExtractor) -> None:
        """Test low confidence entities go through LLM refinement."""
        entities = [
            {"text": "低置信实体", "type": "EVENT", "confidence": 0.3},
        ]

        result = await extractor_with_llm._apply_confidence_grading(entities, "测试文本")

        assert len(result) == 1
        assert result[0]["grading_action"] == "llm_refine"


class TestEntityNormalization:
    """Test entity normalization."""

    def test_normalize_entity_type(self, extractor: GLiNERExtractor) -> None:
        """Test entity type normalization."""
        assert extractor._normalize_type("PERSON") == "PERSON"
        assert extractor._normalize_type("ORG") == "ORG"
        assert extractor._normalize_type("事件") == "EVENT"
        assert extractor._normalize_type("数据指标") == "METRIC"
        assert extractor._normalize_type("法规与政策") == "POLICY"
        assert extractor._normalize_type("产品与技术") == "PRODUCT"
        assert extractor._normalize_type("unknown") == "OTHER"

    def test_normalize_entity_text(self, extractor: GLiNERExtractor) -> None:
        """Test entity text normalization."""
        assert extractor._normalize_text("  测试  ") == "测试"
        assert extractor._normalize_text("") == ""
        assert extractor._normalize_text(None) == ""


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_gliner_disabled(self, config: GLiNERConfig) -> None:
        """Test GLiNER disabled configuration."""
        config.enabled = False

        with patch("gliner.GLiNER") as mock_gliner_class:
            extractor = GLiNERExtractor(config=config)
            entities = await extractor.extract_entities("测试文本")
            assert entities == []

    @pytest.mark.asyncio
    async def test_no_model_loaded(self, config: GLiNERConfig) -> None:
        """Test when GLiNER model fails to load."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_gliner_class.from_pretrained.side_effect = Exception("Load failed")
            extractor = GLiNERExtractor(config=config)

            entities = await extractor.extract_entities("测试文本")
            assert entities == []
