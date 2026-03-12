"""Multi-language spaCy NER extractor."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from core.observability.logging import get_logger

log = get_logger("spacy_extractor")

MODEL_MAP = {
    "zh": "zh_core_web_trf",
    "en": "en_core_web_trf",
    "default": "xx_ent_wiki_sm",
}

SPACY_TO_ENTITY_TYPE = {
    "PER": "人物",
    "PERSON": "人物",
    "ORG": "组织机构",
    "GPE": "地点",
    "LOC": "地点",
    "TIME": "事件",
    "DATE": "事件",
    "EVENT": "事件",
    "CARDINAL": "数据指标",
    "PERCENT": "数据指标",
    "MONEY": "数据指标",
    "LAW": "法规与政策",
}


@dataclass
class SpacyEntity:
    """Entity extracted by spaCy NER.

    Attributes:
        name: Entity text.
        type: Mapped entity type (Chinese label).
        start: Start character offset.
        end: End character offset.
        label: Original spaCy NER label.
    """

    name: str
    type: str
    start: int
    end: int
    label: str


class SpacyExtractor:
    """Multi-language spaCy NER extractor.

    Lazily loads spaCy models per language on first use.
    Deduplicates entities by text and maps spaCy labels
    to domain-specific entity types.
    """

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    @lru_cache(maxsize=3)
    def _load(self, model_name: str) -> object:
        """Load a spaCy model (cached)."""
        import spacy

        return spacy.load(model_name, exclude=["parser", "tagger", "lemmatizer"])

    def _get_nlp(self, language: str) -> object:
        """Get the spaCy NLP pipeline for a language."""
        model = MODEL_MAP.get(language, MODEL_MAP["default"])
        return self._load(model)

    def extract(self, text: str, language: str = "zh") -> list[SpacyEntity]:
        """Extract named entities from text.

        Args:
            text: Input text to analyze.
            language: Language code (zh, en, etc.).

        Returns:
            List of deduplicated SpacyEntity objects.
        """
        nlp = self._get_nlp(language)
        doc = nlp(text)
        seen: set[str] = set()
        results: list[SpacyEntity] = []

        for ent in doc.ents:
            if ent.text in seen:
                continue
            seen.add(ent.text)

            entity_type = SPACY_TO_ENTITY_TYPE.get(ent.label_)
            if not entity_type:
                continue

            results.append(
                SpacyEntity(
                    name=ent.text,
                    type=entity_type,
                    start=ent.start_char,
                    end=ent.end_char,
                    label=ent.label_,
                )
            )

        log.debug(
            "spacy_extracted",
            language=language,
            entity_count=len(results),
        )
        return results
