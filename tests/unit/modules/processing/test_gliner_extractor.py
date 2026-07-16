# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for GLiNER zero-shot entity extractor."""

from __future__ import annotations

import asyncio
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
    """GLiNERExtractor instance with mocked GLiNER.

    Bug-D fix: GLiNERExtractor uses lazy init (_ensure_initialized called on
    first extract_entities). The old fixture returned from inside a `with
    patch("gliner.GLiNER")` block, so the patch was gone by the time the test
    invoked extract_entities → _init_gliner → from gliner import GLiNER got
    the module-level MagicMock (no from_pretrained configured) → _model=None
    → AttributeError on predict_entities.

    Fix: construct the extractor with a pre-populated _model and mark
    _initialized=True so lazy init is skipped entirely. This isolates the
    extractor's behavior from gliner's import-time side effects.
    """
    mock_model = MagicMock()
    ext = GLiNERExtractor(config=config)
    ext._model = mock_model
    ext._initialized = True
    return ext


@pytest.fixture
def extractor_with_llm(config: GLiNERConfig) -> GLiNERExtractor:
    """GLiNERExtractor instance with mocked GLiNER and LLM.

    Bug-D fix: same lazy-init isolation as `extractor` fixture.
    """
    mock_model = MagicMock()
    llm = AsyncMock()
    llm.call_at = AsyncMock(
        return_value={"entities": [{"text": "精炼实体", "type": "EVENT", "confidence": 0.8}]}
    )
    ext = GLiNERExtractor(config=config, llm_client=llm)
    ext._model = mock_model
    ext._initialized = True
    return ext


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


class TestLazyInitConcurrency:
    """Test lazy initialization thread safety (Bug-D HIGH-001/HIGH-1 fix).

    GLiNERExtractor is a singleton shared across pipeline requests. With
    asyncio.to_thread, concurrent first calls can race in _ensure_initialized.
    Fix: threading.Lock + double-checked locking + dedicated ThreadPoolExecutor.
    """

    def test_init_lock_exists(self, config: GLiNERConfig) -> None:
        """GLiNERExtractor has a threading.Lock for init protection."""
        import threading

        ext = GLiNERExtractor(config=config)
        assert hasattr(ext, "_init_lock")
        assert isinstance(ext._init_lock, type(threading.Lock()))

    def test_dedicated_executor_exists(self, config: GLiNERConfig) -> None:
        """GLiNERExtractor uses a dedicated ThreadPoolExecutor (not default pool)."""
        from concurrent.futures import ThreadPoolExecutor

        ext = GLiNERExtractor(config=config)
        assert hasattr(ext, "_executor")
        assert isinstance(ext._executor, ThreadPoolExecutor)

    @pytest.mark.asyncio
    async def test_concurrent_init_loads_model_once(self, config: GLiNERConfig) -> None:
        """Concurrent first calls must trigger model load exactly once."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_model = MagicMock()
            mock_model.predict_entities = MagicMock(return_value=[])
            mock_gliner_class.from_pretrained.return_value = mock_model

            ext = GLiNERExtractor(config=config)

            # Fire 5 concurrent extract_entities calls
            results = await asyncio.gather(*[ext.extract_entities("测试文本") for _ in range(5)])

            # Model should be loaded exactly once despite 5 concurrent calls
            assert mock_gliner_class.from_pretrained.call_count == 1
            # All calls should complete without error
            for r in results:
                assert isinstance(r, list)

    @pytest.mark.asyncio
    async def test_warmup_and_extract_race_loads_once(self, config: GLiNERConfig) -> None:
        """warmup (default pool) + extract (dedicated pool) concurrent → load once.

        This is the real production race scenario: lifecycle.py fires warmup
        on the default asyncio pool, while a user request triggers
        extract_entities on the dedicated gliner pool. Both call
        _ensure_initialized concurrently — the threading.Lock must serialize
        them and ensure from_pretrained is called exactly once.
        """
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_model = MagicMock()
            mock_model.predict_entities = MagicMock(return_value=[])
            mock_gliner_class.from_pretrained.return_value = mock_model

            ext = GLiNERExtractor(config=config)

            # Fire warmup + extract_entities concurrently (different pools)
            await asyncio.gather(
                ext.warmup(),
                ext.extract_entities("测试文本"),
            )

            # Model loaded exactly once despite cross-pool concurrency
            assert mock_gliner_class.from_pretrained.call_count == 1
            assert ext._initialized is True


class TestInitRetryOnFailure:
    """Test that failed init allows retry (Bug-D HIGH-002 fix).

    Old code set _initialized=True BEFORE _init_gliner(), so a failed load
    permanently disabled GLiNER for the process lifetime. Fix: only set
    _initialized=True on success; failure leaves it False to allow retry.
    """

    @pytest.mark.asyncio
    async def test_failed_init_allows_retry(self, config: GLiNERConfig) -> None:
        """Failed initialization should not permanently disable GLiNER."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_model = MagicMock()
            mock_model.predict_entities = MagicMock(return_value=[])
            # First call fails, second call succeeds
            mock_gliner_class.from_pretrained.side_effect = [
                Exception("First load failed"),
                mock_model,
            ]

            ext = GLiNERExtractor(config=config)

            # First call — init fails, returns []
            entities1 = await ext.extract_entities("测试")
            assert entities1 == []
            # _initialized must NOT be True (allows retry)
            assert ext._initialized is False

            # Second call — init retries and succeeds
            entities2 = await ext.extract_entities("测试")
            assert ext._initialized is True
            assert ext._model is mock_model

    @pytest.mark.asyncio
    async def test_permanent_failure_retries_every_call(self, config: GLiNERConfig) -> None:
        """When model load always fails, each call retries (no permanent disable)."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_gliner_class.from_pretrained.side_effect = Exception("Always fails")

            ext = GLiNERExtractor(config=config)

            # Three calls — each should retry loading
            for _ in range(3):
                entities = await ext.extract_entities("测试")
                assert entities == []

            # Model load attempted 3 times (not permanently disabled after first)
            assert mock_gliner_class.from_pretrained.call_count == 3
            assert ext._initialized is False


class TestWarmup:
    """Test warmup() method for pre-initialization (Bug-D HIGH-2 mitigation).

    warmup() allows lifecycle.py to pre-load the model at startup, avoiding
    first-request latency (7-20s). Non-blocking when called via asyncio.
    """

    @pytest.mark.asyncio
    async def test_warmup_initializes_model(self, config: GLiNERConfig) -> None:
        """warmup() should trigger model initialization."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_model = MagicMock()
            mock_gliner_class.from_pretrained.return_value = mock_model

            ext = GLiNERExtractor(config=config)
            assert ext._initialized is False

            await ext.warmup()

            assert ext._initialized is True
            assert ext._model is mock_model

    @pytest.mark.asyncio
    async def test_warmup_after_init_is_noop(self, extractor: GLiNERExtractor) -> None:
        """warmup() on an already-initialized extractor is a no-op."""
        # extractor fixture already has _initialized=True
        original_model = extractor._model
        await extractor.warmup()
        # Model unchanged, no re-init
        assert extractor._model is original_model

    @pytest.mark.asyncio
    async def test_warmup_failure_does_not_mark_initialized(self, config: GLiNERConfig) -> None:
        """warmup() failure should leave _initialized=False for retry."""
        with patch("gliner.GLiNER") as mock_gliner_class:
            mock_gliner_class.from_pretrained.side_effect = Exception("Warmup failed")

            ext = GLiNERExtractor(config=config)
            await ext.warmup()

            assert ext._initialized is False
            assert ext._model is None
