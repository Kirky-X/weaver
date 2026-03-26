# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Multi-language spaCy NER extractor."""

from __future__ import annotations

from dataclasses import dataclass

from core.observability.logging import get_logger

log = get_logger("spacy_extractor")

MODEL_MAP = {
    # zh_core_web_sm is preferred over zh_core_web_trf because:
    # - trf model requires spacy-transformers + PyTorch/TensorFlow
    # - sm model is lighter weight and works out of the box
    # - sm model provides adequate NER accuracy for production use
    "zh": ["zh_core_web_sm", "zh_core_web_trf"],
    "en": ["en_core_web_sm", "en_core_web_trf"],
    "default": ["xx_ent_wiki_sm"],
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

    Supports batch processing via nlp.pipe() for better throughput.
    """

    def __init__(self, batch_size: int = 16, n_process: int = 1) -> None:
        self._models: dict[str, object] = {}
        self._batch_size = batch_size
        self._n_process = n_process

    def _load(self, model_name: str) -> object | None:
        """Load a spaCy model (cached).

        Args:
            model_name: Name of the spaCy model to load.

        Returns:
            Loaded spaCy NLP pipeline or None if loading fails.
        """
        import spacy

        try:
            return spacy.load(model_name, exclude=["parser", "tagger", "lemmatizer"])
        except (OSError, ValueError, ImportError) as e:
            log.warning("spacy_model_load_failed", model=model_name, error=str(e))
            return None

    def _get_nlp(self, language: str) -> object:
        """Get the spaCy NLP pipeline for a language.

        Tries models in order, returns first successfully loaded one.

        Args:
            language: Language code (zh, en, etc.).

        Returns:
            Loaded spaCy NLP pipeline.

        Raises:
            RuntimeError: If no models could be loaded for the language.
        """
        model_candidates = MODEL_MAP.get(language, MODEL_MAP["default"])

        for model in model_candidates:
            nlp = self._load(model)
            if nlp is not None:
                log.debug("spacy_model_loaded", model=model, language=language)
                return nlp

        raise RuntimeError(
            f"No spaCy model available for language '{language}'. Tried: {model_candidates}"
        )

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
        return self._extract_from_doc(doc)

    def extract_batch(
        self,
        texts: list[str],
        language: str = "zh",
    ) -> list[list[SpacyEntity]]:
        """Extract named entities from multiple texts using batch processing.

        Uses nlp.pipe() for efficient batch processing, which is
        significantly faster than processing texts individually.

        Args:
            texts: List of input texts to analyze.
            language: Language code (zh, en, etc.).

        Returns:
            List of entity lists, one per input text.
        """
        if not texts:
            return []

        nlp = self._get_nlp(language)
        results: list[list[SpacyEntity]] = []

        docs = nlp.pipe(
            texts,
            batch_size=self._batch_size,
            n_process=self._n_process,
        )

        for doc in docs:
            results.append(self._extract_from_doc(doc))

        log.debug(
            "spacy_batch_extracted",
            language=language,
            text_count=len(texts),
            total_entities=sum(len(r) for r in results),
        )
        return results

    def _extract_from_doc(self, doc: object) -> list[SpacyEntity]:
        """Extract entities from a spaCy Doc object.

        Args:
            doc: spaCy Doc object.

        Returns:
            List of deduplicated SpacyEntity objects.
        """
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

        return results

    def warmup(self, languages: list[str] | None = None) -> None:
        """Preload models for specified languages.

        Args:
            languages: List of language codes to preload.
                      If None, preloads default models.
        """
        langs = languages or ["zh", "en"]
        for lang in langs:
            try:
                self._get_nlp(lang)
                log.info("spacy_model_warmed_up", language=lang)
            except RuntimeError:
                log.warning("spacy_warmup_failed", language=lang)
