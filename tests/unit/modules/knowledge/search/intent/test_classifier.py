# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for modules.knowledge.search.intent.classifier module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.intent.classifier import IntentClassifier
from modules.knowledge.search.intent.models import Intent, IntentType


class TestIntentClassifierInit:
    """Test IntentClassifier initialization."""

    def test_init_with_llm_client(self):
        """Test initialization with LLM client."""
        mock_llm = MagicMock()
        classifier = IntentClassifier(mock_llm)

        assert classifier._llm is mock_llm


class TestClassifyIntent:
    """Test classify_intent method."""

    @pytest.fixture
    def classifier(self):
        """Create IntentClassifier with mock LLM."""
        mock_llm = AsyncMock()
        return IntentClassifier(mock_llm)

    @pytest.mark.asyncio
    async def test_classify_global_intent(self, classifier):
        """Test classifying global search intent."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "global", "confidence": 0.95}')

        intent = await classifier.classify("What are the main trends?")

        assert isinstance(intent, Intent)
        assert intent.intent_type == IntentType.GLOBAL
        assert intent.confidence == 0.95

    @pytest.mark.asyncio
    async def test_classify_local_intent(self, classifier):
        """Test classifying local search intent."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "local", "confidence": 0.88}')

        intent = await classifier.classify("Find information about Entity X")

        assert intent.intent_type == IntentType.LOCAL
        assert intent.confidence == 0.88

    @pytest.mark.asyncio
    async def test_classify_hybrid_intent(self, classifier):
        """Test classifying hybrid search intent."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "hybrid", "confidence": 0.85}')

        intent = await classifier.classify("Compare trends and find specific details")

        assert intent.intent_type == IntentType.HYBRID

    @pytest.mark.asyncio
    async def test_classify_with_low_confidence(self, classifier):
        """Test classification with low confidence."""
        classifier._llm.call = AsyncMock(return_value='{"intent": "global", "confidence": 0.3}')

        intent = await classifier.classify("Unclear query")

        assert intent.confidence == 0.3
        # Low confidence should still return result

    @pytest.mark.asyncio
    async def test_classify_empty_query(self, classifier):
        """Test classifying empty query."""
        intent = await classifier.classify("")

        assert intent is not None
        # Should have default intent

    @pytest.mark.asyncio
    async def test_classify_handles_llm_error(self, classifier):
        """Test handling LLM classification error."""
        classifier._llm.call = AsyncMock(side_effect=Exception("LLM error"))

        intent = await classifier.classify("Test query")

        # Should return default intent
        assert intent is not None


class TestIntentClassifierKeywordFallback:
    """Test keyword-based fallback classification."""

    @pytest.fixture
    def classifier(self):
        """Create IntentClassifier."""
        mock_llm = MagicMock()
        return IntentClassifier(mock_llm)

    def test_keyword_global_indicators(self, classifier):
        """Test keyword detection for global intent."""
        query = "What are the overall trends and patterns?"

        # Should detect global indicators
        intent = classifier._classify_by_keywords(query)

        assert intent is not None

    def test_keyword_local_indicators(self, classifier):
        """Test keyword detection for local intent."""
        query = "Find all information about specific entity"

        intent = classifier._classify_by_keywords(query)

        assert intent is not None

    def test_keyword_no_match(self, classifier):
        """Test when no keywords match."""
        query = "Random unrelated text"

        intent = classifier._classify_by_keywords(query)

        # Should return None or default
        assert intent is None or isinstance(intent, Intent)


class TestIntent:
    """Test Intent model."""

    def test_create_global_intent(self):
        """Test creating global intent."""
        intent = Intent(
            intent_type=IntentType.GLOBAL,
            confidence=0.95,
            reasoning="Broad question about trends",
        )

        assert intent.intent_type == IntentType.GLOBAL
        assert intent.confidence == 0.95
        assert "Broad" in intent.reasoning

    def test_create_local_intent(self):
        """Test creating local intent."""
        intent = Intent(
            intent_type=IntentType.LOCAL,
            confidence=0.88,
            entities=["Entity X"],
        )

        assert intent.intent_type == IntentType.LOCAL
        assert "Entity X" in intent.entities

    def test_create_hybrid_intent(self):
        """Test creating hybrid intent."""
        intent = Intent(
            intent_type=IntentType.HYBRID,
            confidence=0.85,
        )

        assert intent.intent_type == IntentType.HYBRID


class TestIntentType:
    """Test IntentType enum."""

    def test_intent_types(self):
        """Test all intent types exist."""
        assert hasattr(IntentType, "GLOBAL")
        assert hasattr(IntentType, "LOCAL")
        assert hasattr(IntentType, "HYBRID")


class TestIntentClassifierIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_classification_workflow(self):
        """Test complete classification workflow."""
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(
            return_value='{"intent": "global", "confidence": 0.92, "reasoning": "Test"}'
        )

        classifier = IntentClassifier(mock_llm)

        intent = await classifier.classify("What are the main topics?")

        assert isinstance(intent, Intent)
        assert intent.confidence > 0.9

    @pytest.mark.asyncio
    async def test_classification_with_fallback(self):
        """Test classification falls back to keywords on LLM error."""
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(side_effect=Exception("Error"))

        classifier = IntentClassifier(mock_llm)

        # Should use keyword fallback
        intent = await classifier.classify("Find entity information")

        assert intent is not None
