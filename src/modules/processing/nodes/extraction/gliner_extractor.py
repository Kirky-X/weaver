# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from core.constants import EntityType
from core.llm.types import CallPoint
from core.observability import get_logger
from core.utils.paths import CONFIG_DIR
from core.utils.toml_loader import load_toml_or_warn

if __name__ != "__main__":
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from core.llm.client import LLMClient

log = get_logger(__name__)

ENTITY_TYPES_FILE = CONFIG_DIR / "entity_types.toml"


def _gliner_config_data() -> dict[str, Any]:
    """Load the [gliner] table from config/entity_types.toml once (cached).

    Cached because GLiNERConfig labels and ``_normalize_type`` need it and the
    file is static reference data; a plain module cache avoids re-reading the
    TOML on every extractor call.
    """
    cached = getattr(_gliner_config_data, "_cache", None)
    if cached is None:
        cached = load_toml_or_warn(ENTITY_TYPES_FILE, event="entity_types_config").get("gliner", {})
        _gliner_config_data._cache = cached  # type: ignore[attr-defined]
    return cached


def _gliner_default_labels() -> list[str]:
    """Default GLiNER custom labels from config (validated against EntityType).

    Unknown labels are dropped with a warning so a stale config cannot ask the
    model for a type the downstream normalization does not understand.
    """
    allowed = {t.value for t in EntityType}
    labels: list[str] = []
    for label in _gliner_config_data().get("labels") or []:
        if label not in allowed:
            log.warning("gliner_label_not_entity_type", label=label)
            continue
        labels.append(str(label))
    return labels


def _gliner_type_map() -> dict[str, str]:
    """Load GLiNER/spaCy label → internal code map from config (loaded once)."""
    return {str(k): str(v) for k, v in (_gliner_config_data().get("type_map") or {}).items()}


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
    labels: list[str] = field(default_factory=_gliner_default_labels)


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
        self._initialized = False
        # threading.Lock (not asyncio.Lock) because _ensure_initialized runs
        # inside asyncio.to_thread → on a worker thread, not the event loop.
        self._init_lock = threading.Lock()
        # Dedicated single-worker pool: serializes model access (thread-safety),
        # limits memory (one inference at a time), avoids starving the default
        # asyncio pool shared by spaCy/DuckDB/SSL.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gliner")

    def _ensure_initialized(self) -> None:
        """Lazy initialize GLiNER model on first use (thread-safe).

        Defers heavy `import gliner` (which triggers `import transformers`)
        from startup to first extraction call, preventing startup blockage.

        Uses double-checked locking so concurrent first calls (via
        asyncio.to_thread) only load the model once. On failure, leaves
        _initialized=False to allow retry on subsequent calls.
        """
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            if self._config.enabled:
                try:
                    self._init_gliner()
                    # Only mark initialized on success — allows retry on failure
                    self._initialized = True
                except Exception as exc:
                    log.warning(
                        "gliner_model_init_failed_will_retry",
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )
                    self._model = None
                    return
            else:
                self._initialized = True

    def _init_gliner(self) -> None:
        """Initialize GLiNER model (raises on failure for retry semantics)."""
        from gliner import GLiNER

        self._model = GLiNER.from_pretrained(self._config.model_name)
        log.info(
            "gliner_model_initialized",
            model=self._config.model_name,
        )

    async def warmup(self) -> None:
        """Pre-initialize the model to avoid first-request latency.

        Call from lifecycle.py at startup (fire-and-forget or awaited) to
        shift the 7-20s model load from first user request to startup.
        Safe to call multiple times; no-op after successful init.
        """
        await asyncio.to_thread(self._ensure_initialized)

    async def extract_entities(self, text: str) -> list[dict[str, Any]]:
        """Extract entities using GLiNER.

        Args:
            text: Input text to extract entities from.

        Returns:
            List of extracted entities with text, type, and confidence.
        """
        # Run lazy init + prediction in dedicated thread to avoid blocking the
        # event loop. GLiNER.from_pretrained() and predict_entities() are
        # synchronous and CPU/IO-intensive — calling them directly in an async
        # context blocks the entire server (observed: API unresponsive for
        # minutes). Dedicated executor (max_workers=1) serializes model access.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._extract_entities_sync, text)

    def _extract_entities_sync(self, text: str) -> list[dict[str, Any]]:
        """Synchronous entity extraction (runs in thread executor)."""
        self._ensure_initialized()
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
        spacy_entities: list[Any],
        gliner_entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge spaCy and GLiNER entities, removing duplicates.

        spaCy entities may be ``SpacyEntity`` dataclasses (with ``.name``/
        ``.type`` attributes) or pre-converted dicts; both are normalized
        to the dict contract used below.

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
            if isinstance(entity, dict):
                item = dict(entity)
            else:
                # SpacyEntity dataclass has no .text/.confidence fields
                item = {
                    "text": getattr(entity, "name", ""),
                    "type": getattr(entity, "type", ""),
                    "confidence": 1.0,
                }
            key = item["text"].lower().strip()
            if key:
                entity_map[key] = item

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
            CallPoint.ENTITY_REFINE,
            {
                "entity": entity["text"],
                "type": entity["type"],
                "context": context[:1500],  # Truncate for LLM
            },
        )

        # Update entity with refined data. Without output_model the LLM
        # result may be a raw string or a dict missing "entities" — guard
        # instead of raising AttributeError/KeyError.
        if isinstance(result, dict) and result.get("entities"):
            refined = result["entities"][0]
            if isinstance(refined, dict):
                entity["text"] = refined.get("text", entity["text"])
                entity["confidence"] = refined.get("confidence", entity["confidence"])
        elif not isinstance(result, dict):
            log.warning(
                "entity_refine_unexpected_result",
                result_type=type(result).__name__,
            )

        return entity

    def _normalize_type(self, label: str) -> str:
        """Normalize entity type label.

        Args:
            label: Raw label from GLiNER or spaCy.

        Returns:
            Normalized type string.
        """
        # type_map is loaded once from config/entity_types.toml ([gliner.type_map])
        # at first use and cached, instead of rebuilt on every call.
        return _gliner_type_map().get(label, "OTHER")

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
