# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM-based intent classifier following MAGMA intent taxonomy."""

from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger

from .schemas import IntentClassification, QueryIntent, TemporalSignal

log = get_logger("search.intent.classifier")

INTENT_CLASSIFICATION_PROMPT = """你是一个查询意图分类器。分析用户的搜索查询，识别其主要意图类型。

意图类型：
- WHY: 询问原因、理由、因果关系（"为什么..."、"因为什么..."、"原因是什么..."）
- WHEN: 询问时间、时间点、顺序（"什么时候..."、"何时..."、"哪个时间..."）
- ENTITY: 询问实体、事实、描述（"X是什么..."、"告诉我关于Y..."）
- MULTI_HOP: 需要多步推理的关系查询（"X和Y的关系..."、"对比X和Z..."）
- OPEN: 开放域、探索性查询（"关于..."、"告诉我..."）

同时检测：
1. 时间信号：识别任何相对时间表达式（如"yesterday"、"last week"、"next Monday"）
2. 实体信号：提取主要实体名称

返回 JSON：
{
    "intent": "WHY|WHEN|ENTITY|MULTI_HOP|OPEN",
    "confidence": 0.0-1.0,
    "temporal_signals": [{"expression": "yesterday", "anchor_type": "relative"}],
    "entity_signals": ["实体1", "实体2"],
    "keywords": ["关键", "词"]
}

查询：{query}"""


class IntentClassifier:
    """LLM-based intent classifier following MAGMA intent taxonomy."""

    def __init__(self, llm: LLMClient) -> None:
        """Initialize intent classifier.

        Args:
            llm: LLM client for classification.
        """
        self._llm = llm

    async def classify(self, query: str) -> IntentClassification:
        """Classify query intent with confidence and extract signals.

        Args:
            query: The user's search query.

        Returns:
            IntentClassification with detected intent, confidence, and extracted signals.
        """
        try:
            response = await self._llm.call(
                call_point=CallPoint.SEARCH_LOCAL,
                payload={
                    "query": query,
                    "context": INTENT_CLASSIFICATION_PROMPT,
                    "phase": "intent_classification",
                },
            )

            # Parse LLM JSON response
            if isinstance(response, str):
                import json

                result = json.loads(response)
            else:
                result = response

            intent_str = result.get("intent", "OPEN").lower()
            try:
                intent = QueryIntent(intent_str)
            except ValueError:
                intent = QueryIntent.OPEN

            return IntentClassification(
                intent=intent,
                confidence=float(result.get("confidence", 0.5)),
                temporal_signals=self._extract_temporal_signals(result.get("temporal_signals", [])),
                entity_signals=result.get("entity_signals"),
                keywords=result.get("keywords"),
            )
        except Exception as exc:
            log.error("intent_classification_failed", query=query, error=str(exc))
            # Fallback to OPEN intent on error
            return IntentClassification(
                intent=QueryIntent.OPEN,
                confidence=0.0,
                temporal_signals=None,
                entity_signals=None,
                keywords=None,
            )

    def _extract_temporal_signals(self, signals: list) -> list[TemporalSignal]:
        """Extract temporal signals from LLM response."""
        temporal_signals = []
        for signal in signals:
            if isinstance(signal, dict):
                temporal_signals.append(TemporalSignal(**signal))
        return temporal_signals
