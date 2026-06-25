# Copyright (c) 2026 KirkyX. All Rights Reserved
"""GLiNER zero-shot entity extractor.

Uses spaCy + GLiNER dual engine for entity extraction:
- spaCy: Standard types (PERSON/ORG/GPE/LOC)
- GLiNER: Custom types (事件/数据指标/法规与政策/产品与技术)

Three-level confidence pipeline:
- ≥ 0.7: Direct store
- 0.4-0.7: Vector linking
- < 0.4: LLM refinement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.observability import get_logger

if __name__ != "__main__":
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from core.llm.client import LLMClient

log = get_logger(__name__)


@dataclass
class GLiNERConfig:
    """Configuration for GLiNER zero-shot entity extraction.

    Attributes:
        enabled: Whether to use GLiNER for entity extraction.
        model_name: GLiNER model name.
        threshold: Confidence threshold for entity extraction.
        max_input_length: Maximum input text length.
        labels: Custom entity type labels for GLiNER.
    """

    enabled: bool = True
    model_name: str = "urchade/gliner_multi-v2.1"
    threshold: float = 0.5
    max_input_length: int = 4096
    labels: list[str] = field(
        default_factory=lambda: ["事件", "数据指标", "法规与政策", "产品", "概念"]
    )


class GLiNERExtractor:
    """GLiNER zero-shot entity extractor.

    Uses GLiNER for custom entity type extraction (事件/数据指标/法规与政策/产品与技术).
    Integrates with spaCy NER for standard types.

    Implements:
        GLiNERExtractor: Zero-shot entity extraction
    """

    def __init__(
        self,
        config: GLiNERConfig | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """Initialize GLiNERExtractor.

        Args:
            config: Extractor configuration. Uses defaults if None.
            llm_client: LLM client for entity refinement (optional).
        """
        self._config = config or GLiNERConfig()
        self._llm_client = llm_client
        self._model = None

        # Initialize GLiNER if enabled
        if self._config.enabled:
            self._init_gliner()

    def _init_gliner(self) -> None:
        """Initialize GLiNER model."""
        try:
            from gliner import GLiNER

            self._model = GLiNER.from_pretrained(self._config.model_name)
            log.info(
                "gliner_model_initialized",
                model=self._config.model_name,
            )
        except Exception as exc:
            log.warning(
                "gliner_model_init_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            self._model = None

    async def extract_entities(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using GLiNER.

        Args:
            text: Input text to extract entities from.

        Returns:
            List of extracted entities with text, type, and confidence.
        """
        if not text or not self._config.enabled or self._model is None:
            return []

        try:
            # Truncate text to max input length
            truncated_text = text[: self._config.max_input_length]

            # Extract entities using GLiNER
            raw_entities = self._model.predict_entities(
                truncated_text,
                labels=self._config.labels,
                threshold=self._config.threshold,
            )

            # Normalize entities
            entities = []
            for entity in raw_entities:
                normalized = {
                    "text": self._normalize_text(entity.get("text", "")),
                    "type": self._normalize_type(entity.get("label", "")),
                    "confidence": entity.get("score", 0.0),
                    "source": "gliner",
                }
                if normalized["text"]:
                    entities.append(normalized)

            return entities

        except Exception as exc:
            log.warning(
                "gliner_extraction_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return []

    def _merge_entities(
        self,
        spacy_entities: list[dict[str, Any]],
        gliner_entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge spaCy and GLiNER entities, removing duplicates.

        Args:
            spacy_entities: Entities from spaCy NER.
            gliner_entities: Entities from GLiNER.

        Returns:
            Merged entity list without duplicates.
        """
        # Create lookup by normalized text
        entity_map: dict[str, dict[str, Any]] = {}

        # Add spaCy entities first (higher priority for standard types)
        for entity in spacy_entities:
            key = entity["text"].lower().strip()
            if key:
                entity_map[key] = entity

        # Add GLiNER entities (skip duplicates, keep higher confidence)
        for entity in gliner_entities:
            key = entity["text"].lower().strip()
            if key:
                if key in entity_map:
                    # Keep higher confidence
                    if entity["confidence"] > entity_map[key]["confidence"]:
                        entity_map[key] = entity
                else:
                    entity_map[key] = entity

        return list(entity_map.values())

    async def _apply_confidence_grading(
        self,
        entities: list[dict[str, Any]],
        context: str,
    ) -> list[dict[str, Any]]:
        """Apply confidence grading (three-level pipeline).

        Args:
            entities: List of extracted entities.
            context: Text context for refinement.

        Returns:
            List of graded entities with grading_action field.
        """
        graded_entities = []

        for entity in entities:
            confidence = entity["confidence"]

            if confidence >= 0.7:
                # High confidence: direct store
                entity["grading_action"] = "direct_store"
                graded_entities.append(entity)

            elif confidence >= 0.4:
                # Medium confidence: vector linking
                entity["grading_action"] = "vector_link"
                graded_entities.append(entity)

            else:
                # Low confidence: LLM refinement
                if self._llm_client:
                    try:
                        refined = await self._llm_refine(entity, context)
                        refined["grading_action"] = "llm_refine"
                        graded_entities.append(refined)
                    except Exception as exc:
                        log.warning(
                            "llm_refine_failed",
                            entity=entity["text"],
                            error=str(exc),
                        )
                        entity["grading_action"] = "llm_refine_failed"
                        graded_entities.append(entity)
                else:
                    entity["grading_action"] = "no_llm_available"
                    graded_entities.append(entity)

        return graded_entities

    async def _llm_refine(
        self,
        entity: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        """Refine entity using LLM.

        Args:
            entity: Entity to refine.
            context: Text context.

        Returns:
            Refined entity.
        """
        if not self._llm_client:
            return entity

        result = await self._llm_client.call_at(
            "entity_refine",
            {
                "entity": entity["text"],
                "type": entity["type"],
                "context": context[:1500],  # Truncate for LLM
            },
        )

        # Update entity with refined data
        if result.get("entities"):
            refined = result["entities"][0]
            entity["text"] = refined.get("text", entity["text"])
            entity["confidence"] = refined.get("confidence", entity["confidence"])

        return entity

    def _normalize_type(self, label: str) -> str:
        """Normalize entity type label.

        Args:
            label: Raw label from GLiNER or spaCy.

        Returns:
            Normalized type string.
        """
        type_map = {
            "PERSON": "PERSON",
            "ORG": "ORG",
            "GPE": "GPE",
            "LOC": "LOC",
            "事件": "EVENT",
            "数据指标": "METRIC",
            "法规与政策": "POLICY",
            "产品与技术": "PRODUCT",
        }
        return type_map.get(label, "OTHER")

    def _normalize_text(self, text: str | None) -> str:
        """Normalize entity text.

        Args:
            text: Raw entity text.

        Returns:
            Normalized text.
        """
        if not text:
            return ""
        return text.strip()
