# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for intent classifier module."""

from unittest.mock import AsyncMock

import pytest

from modules.knowledge.search.intent.schemas import (
    IntentClassification,
    QueryIntent,
    TemporalSignal,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_basic_why_query():
    """Test classification of WHY intent queries."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = """{
        "intent": "why",
        "confidence": 0.85,
        "temporal_signals": [],
        "entity_signals": [],
        "keywords": ["原因", "服务器"]
    }"""

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("为什么服务器会崩溃？")

    assert result.intent == QueryIntent.WHY
    assert result.confidence == 0.85
    assert result.keywords == ["原因", "服务器"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_when_query():
    """Test classification of WHEN intent queries."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = """{
        "intent": "when",
        "confidence": 0.9,
        "temporal_signals": [{"expression": "yesterday", "anchor_type": "relative"}],
        "entity_signals": [],
        "keywords": ["时间", "发生了什么"]
    }"""

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("昨天发生了什么？")

    assert result.intent == QueryIntent.WHEN
    assert result.confidence == 0.9
    assert len(result.temporal_signals) == 1
    assert result.temporal_signals[0].expression == "yesterday"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_entity_query():
    """Test classification of ENTITY intent queries."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = """{
        "intent": "entity",
        "confidence": 0.75,
        "temporal_signals": [],
        "entity_signals": ["Neo4j", "图数据库"],
        "keywords": ["Neo4j"]
    }"""

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("Neo4j是什么？")

    assert result.intent == QueryIntent.ENTITY
    assert result.confidence == 0.75
    assert result.entity_signals == ["Neo4j", "图数据库"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_multi_hop_query():
    """Test classification of MULTI_HOP intent queries."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = """{
        "intent": "multi_hop",
        "confidence": 0.8,
        "temporal_signals": [],
        "entity_signals": ["GraphRAG", "MAGMA"],
        "keywords": ["区别", "对比"]
    }"""

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("GraphRAG和MAGMA有什么区别？")

    assert result.intent == QueryIntent.MULTI_HOP
    assert result.confidence == 0.8
    assert result.entity_signals == ["GraphRAG", "MAGMA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_open_query():
    """Test classification of OPEN intent queries."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = """{
        "intent": "open",
        "confidence": 0.6,
        "temporal_signals": [],
        "entity_signals": [],
        "keywords": ["知识图谱", "搜索"]
    }"""

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("关于知识图谱的技术")

    assert result.intent == QueryIntent.OPEN
    assert result.confidence == 0.6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_fallback_on_error():
    """Test that classifier falls back to OPEN on error."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.side_effect = Exception("LLM service unavailable")

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("test query")

    assert result.intent == QueryIntent.OPEN
    assert result.confidence == 0.0
    assert result.temporal_signals is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_dict_response():
    """Test classifier handles dict response from LLM."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = {
        "intent": "why",
        "confidence": 0.7,
        "temporal_signals": [],
        "entity_signals": None,
        "keywords": None,
    }

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("为什么出错？")

    assert result.intent == QueryIntent.WHY
    assert result.confidence == 0.7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_invalid_intent_fallback():
    """Test classifier falls back to OPEN for unknown intent string."""
    from modules.knowledge.search.intent.classifier import IntentClassifier

    llm = AsyncMock()
    llm.call.return_value = '{"intent": "unknown_type", "confidence": 0.3, "temporal_signals": [], "entity_signals": [], "keywords": []}'

    classifier = IntentClassifier(llm=llm)
    result = await classifier.classify("random query")

    assert result.intent == QueryIntent.OPEN
