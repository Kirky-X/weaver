# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for modules.knowledge.search.intent.classifier module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.intent.classifier import IntentClassifier
from modules.knowledge.search.intent.schemas import (
    IntentClassification,
    QueryIntent,
    TemporalSignal,
)


class TestIntentClassifierInit:
    """Test IntentClassifier initialization."""

    def test_init_with_llm_client(self):
        """Test initialization with LLM client."""
        mock_llm = MagicMock()
        classifier = IntentClassifier(mock_llm)

        assert classifier._llm is mock_llm


class TestClassify:
    """Test classify method."""

    @pytest.fixture
    def classifier(self):
        """Create IntentClassifier with mock LLM."""
        mock_llm = AsyncMock()
        return IntentClassifier(mock_llm)

    @pytest.mark.asyncio
    async def test_classify_why_intent(self, classifier):
        """Test classifying WHY intent."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "why", "confidence": 0.95, "keywords": ["原因"]}'
        )

        result = await classifier.classify("为什么会发生这件事?")

        assert isinstance(result, IntentClassification)
        assert result.intent == QueryIntent.WHY
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_classify_when_intent(self, classifier):
        """Test classifying WHEN intent."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "when", "confidence": 0.88, "temporal_signals": [{"expression": "yesterday", "anchor_type": "relative"}]}'
        )

        result = await classifier.classify("昨天发生了什么?")

        assert result.intent == QueryIntent.WHEN
        assert result.confidence == 0.88
        assert result.temporal_signals is not None
        assert len(result.temporal_signals) == 1

    @pytest.mark.asyncio
    async def test_classify_entity_intent(self, classifier):
        """Test classifying ENTITY intent."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "entity", "confidence": 0.92, "entity_signals": ["苹果公司"]}'
        )

        result = await classifier.classify("苹果公司是什么?")

        assert result.intent == QueryIntent.ENTITY
        assert result.entity_signals == ["苹果公司"]

    @pytest.mark.asyncio
    async def test_classify_multi_hop_intent(self, classifier):
        """Test classifying MULTI_HOP intent."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "multi_hop", "confidence": 0.85}')

        result = await classifier.classify("X和Y之间有什么关系?")

        assert result.intent == QueryIntent.MULTI_HOP

    @pytest.mark.asyncio
    async def test_classify_open_intent(self, classifier):
        """Test classifying OPEN intent."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "open", "confidence": 0.75}')

        result = await classifier.classify("告诉我一些有趣的事情")

        assert result.intent == QueryIntent.OPEN

    @pytest.mark.asyncio
    async def test_classify_invalid_intent_defaults_to_open(self, classifier):
        """Test invalid intent defaults to OPEN."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "invalid_type", "confidence": 0.5}'
        )

        result = await classifier.classify("Test query")

        assert result.intent == QueryIntent.OPEN

    @pytest.mark.asyncio
    async def test_classify_handles_llm_error(self, classifier):
        """Test handling LLM classification error."""
        classifier._llm.call = AsyncMock(side_effect=Exception("LLM error"))

        result = await classifier.classify("Test query")

        # Should return OPEN intent as fallback
        assert result.intent == QueryIntent.OPEN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_classify_with_keywords(self, classifier):
        """Test classification with keywords extraction."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "entity", "confidence": 0.9, "keywords": ["人工智能", "发展"]}'
        )

        result = await classifier.classify("人工智能的发展趋势")

        assert result.keywords == ["人工智能", "发展"]

    @pytest.mark.asyncio
    async def test_classify_with_temporal_signals(self, classifier):
        """Test classification with temporal signals."""
        classifier._llm.call = AsyncMock(
            return_value='{"intent": "when", "confidence": 0.88, "temporal_signals": [{"expression": "last week", "anchor_type": "relative"}]}'
        )

        result = await classifier.classify("上周发生了什么?")

        assert result.temporal_signals is not None
        assert len(result.temporal_signals) == 1
        assert isinstance(result.temporal_signals[0], TemporalSignal)
        assert result.temporal_signals[0].expression == "last week"


class TestExtractTemporalSignals:
    """Test _extract_temporal_signals method."""

    @pytest.fixture
    def classifier(self):
        """Create IntentClassifier with mock LLM."""
        mock_llm = MagicMock()
        return IntentClassifier(mock_llm)

    def test_extract_valid_signals(self, classifier):
        """Test extracting valid temporal signals."""
        signals = [
            {"expression": "yesterday", "anchor_type": "relative"},
            {"expression": "2024-01-01", "anchor_type": "absolute"},
        ]

        result = classifier._extract_temporal_signals(signals)

        assert len(result) == 2
        assert all(isinstance(s, TemporalSignal) for s in result)

    def test_extract_empty_signals(self, classifier):
        """Test extracting empty signals list."""
        result = classifier._extract_temporal_signals([])

        assert result == []

    def test_extract_non_dict_signals_skipped(self, classifier):
        """Test non-dict signals are skipped."""
        signals = [
            {"expression": "yesterday", "anchor_type": "relative"},
            "invalid",
            123,
        ]

        result = classifier._extract_temporal_signals(signals)

        assert len(result) == 1
        assert result[0].expression == "yesterday"


class TestIntentClassification:
    """Test IntentClassification model."""

    def test_create_basic_classification(self):
        """Test creating basic classification."""
        classification = IntentClassification(
            intent=QueryIntent.ENTITY,
            confidence=0.95,
        )

        assert classification.intent == QueryIntent.ENTITY
        assert classification.confidence == 0.95

    def test_create_with_temporal_signals(self):
        """Test creating classification with temporal signals."""
        signals = [TemporalSignal(expression="yesterday", anchor_type="relative")]
        classification = IntentClassification(
            intent=QueryIntent.WHEN,
            confidence=0.88,
            temporal_signals=signals,
        )

        assert classification.temporal_signals == signals

    def test_create_with_entity_signals(self):
        """Test creating classification with entity signals."""
        classification = IntentClassification(
            intent=QueryIntent.ENTITY,
            confidence=0.92,
            entity_signals=["苹果公司", "特斯拉"],
        )

        assert classification.entity_signals == ["苹果公司", "特斯拉"]

    def test_create_with_keywords(self):
        """Test creating classification with keywords."""
        classification = IntentClassification(
            intent=QueryIntent.OPEN,
            confidence=0.75,
            keywords=["人工智能", "机器学习"],
        )

        assert classification.keywords == ["人工智能", "机器学习"]


class TestQueryIntent:
    """Test QueryIntent enum."""

    def test_all_intent_types(self):
        """Test all intent types exist."""
        assert QueryIntent.WHY.value == "why"
        assert QueryIntent.WHEN.value == "when"
        assert QueryIntent.ENTITY.value == "entity"
        assert QueryIntent.MULTI_HOP.value == "multi_hop"
        assert QueryIntent.OPEN.value == "open"

    def test_intent_from_string(self):
        """Test creating intent from string."""
        assert QueryIntent("why") == QueryIntent.WHY
        assert QueryIntent("when") == QueryIntent.WHEN
        assert QueryIntent("entity") == QueryIntent.ENTITY

    def test_invalid_intent_raises(self):
        """Test invalid intent raises ValueError."""
        with pytest.raises(ValueError):
            QueryIntent("invalid")


class TestTemporalSignal:
    """Test TemporalSignal model."""

    def test_create_relative_signal(self):
        """Test creating relative temporal signal."""
        signal = TemporalSignal(
            expression="yesterday",
            anchor_type="relative",
        )

        assert signal.expression == "yesterday"
        assert signal.anchor_type == "relative"
        assert signal.resolved_timestamp is None

    def test_create_absolute_signal(self):
        """Test creating absolute temporal signal."""
        from datetime import UTC, datetime

        ts = datetime(2024, 1, 1, tzinfo=UTC)
        signal = TemporalSignal(
            expression="2024-01-01",
            anchor_type="absolute",
            resolved_timestamp=ts,
        )

        assert signal.anchor_type == "absolute"
        assert signal.resolved_timestamp == ts


class TestIntentClassifierIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_classification_workflow(self):
        """Test complete classification workflow."""
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(
            return_value='{"intent": "entity", "confidence": 0.92, "entity_signals": ["测试实体"], "keywords": ["关键词"]}'
        )

        classifier = IntentClassifier(mock_llm)

        result = await classifier.classify("测试实体是什么?")

        assert isinstance(result, IntentClassification)
        assert result.intent == QueryIntent.ENTITY
        assert result.confidence > 0.9

    @pytest.mark.asyncio
    async def test_classification_fallback_on_error(self):
        """Test classification falls back to OPEN on error."""
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(side_effect=Exception("Connection error"))

        classifier = IntentClassifier(mock_llm)

        result = await classifier.classify("Any query")

        assert result.intent == QueryIntent.OPEN
        assert result.confidence == 0.0
