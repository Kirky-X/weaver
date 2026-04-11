# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Multi-language spaCy NER extractor."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.observability.logging import get_logger

log = get_logger("spacy_extractor")

MODEL_MAP = {
    # zh_core_web_lg is preferred over zh_core_web_trf because:
    # - trf model requires spacy-transformers + PyTorch/TensorFlow
    # - lg model provides better NER accuracy for production use
    "zh": ["zh_core_web_lg", "zh_core_web_trf"],
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


# Maximum wheel file size (1GB) to prevent zip bomb attacks
MAX_WHEEL_SIZE = 1 * 1024 * 1024 * 1024


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
        self._temp_dirs: list[str] = []  # Track extracted wheel directories

    def cleanup(self) -> None:
        """Clean up temporary directories created during wheel extraction."""
        import shutil

        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._temp_dirs.clear()

    def _extract_wheel_safely(self, wheel_path: str) -> str | None:
        """Extract a wheel file safely with path traversal and size checks.

        Args:
            wheel_path: Path to the .whl file.

        Returns:
            Path to extracted directory, or None if extraction failed.
        """
        import shutil
        import tempfile
        import zipfile

        wheel = Path(wheel_path)

        # Zip bomb protection: check file size
        wheel_size = wheel.stat().st_size
        if wheel_size > MAX_WHEEL_SIZE:
            log.warning(
                "spacy_wheel_size_exceeded",
                wheel_path=wheel_path,
                size=wheel_size,
                max_size=MAX_WHEEL_SIZE,
            )
            return None

        # Create temp directory
        extract_dir = tempfile.mkdtemp(prefix="spacy_model_")
        extract_path = Path(extract_dir)

        try:
            with zipfile.ZipFile(wheel_path, "r") as zf:
                # Path traversal protection: verify all members resolve within extract_dir
                for member in zf.namelist():
                    member_path = (extract_path / member).resolve()
                    if not str(member_path).startswith(str(extract_path.resolve())):
                        log.warning(
                            "spacy_wheel_path_traversal",
                            wheel_path=wheel_path,
                            malicious_member=member,
                        )
                        return None

                # Safe to extract
                zf.extractall(extract_dir)

            # Track for cleanup
            self._temp_dirs.append(extract_dir)
            return extract_dir

        except (zipfile.BadZipFile, OSError) as e:
            log.warning("spacy_wheel_extract_failed", wheel_path=wheel_path, error=str(e))
            shutil.rmtree(extract_dir, ignore_errors=True)
            return None

    def _load(self, model_name: str) -> object | None:
        """Load a spaCy model (cached).

        Supports loading from:
        1. Local wheel file (via SPACY_ZH_MODEL_PATH or SPACY_EN_MODEL_PATH env var)
           - Extracts wheel safely to temp directory and loads from extracted path
        2. Local model directory (already extracted)
        3. Installed spaCy model name

        Args:
            model_name: Name of the spaCy model to load.

        Returns:
            Loaded spaCy NLP pipeline or None if loading fails.
        """
        import spacy

        # Determine env var based on model language
        env_var = None
        if model_name.startswith("zh_core_web"):
            env_var = "SPACY_ZH_MODEL_PATH"
        elif model_name.startswith("en_core_web"):
            env_var = "SPACY_EN_MODEL_PATH"

        # Check for local model path (wheel file or directory)
        if env_var:
            local_path = os.getenv(env_var)
            if local_path:
                path = Path(local_path)
                if path.exists():
                    # Case 1: .whl file - extract and load
                    if path.suffix == ".whl" and path.is_file():
                        extract_dir = self._extract_wheel_safely(local_path)
                        if extract_dir:
                            # Find the model directory inside extracted wheel
                            # Wheel contains a directory named exactly like the model prefix
                            model_prefix = model_name.split("-")[0]
                            for name in os.listdir(extract_dir):
                                if name == model_prefix or name.startswith(f"{model_prefix}-"):
                                    model_dir = os.path.join(extract_dir, name)
                                    if os.path.isdir(model_dir):
                                        nlp = spacy.load(
                                            model_dir,
                                            exclude=["parser", "tagger", "lemmatizer"],
                                        )
                                        log.info(
                                            "spacy_model_loaded_from_wheel",
                                            wheel_path=local_path,
                                            extracted_to=model_dir,
                                        )
                                        return nlp

                            log.warning(
                                "spacy_wheel_extract_no_model_dir",
                                wheel_path=local_path,
                                expected=model_prefix,
                                contents=os.listdir(extract_dir),
                            )

                    # Case 2: Directory - load directly
                    elif path.is_dir():
                        try:
                            nlp = spacy.load(
                                local_path,
                                exclude=["parser", "tagger", "lemmatizer"],
                            )
                            log.info("spacy_model_loaded_from_local", path=local_path)
                            return nlp
                        except (OSError, ValueError, ImportError) as e:
                            log.info(
                                "spacy_local_load_skipped",
                                path=local_path,
                                error=str(e),
                            )

        # Case 3: Fallback to installed model
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

    def extract(
        self, text: str, language: str = "zh", disable_data_metrics: bool = False
    ) -> list[SpacyEntity]:
        """Extract named entities from text.

        Args:
            text: Input text to analyze.
            language: Language code (zh, en, etc.).
            disable_data_metrics: Skip '数据指标' type entities when True.

        Returns:
            List of deduplicated SpacyEntity objects.
        """
        nlp = self._get_nlp(language)
        doc = nlp(text)
        return self._extract_from_doc(doc, disable_data_metrics)

    def extract_batch(
        self,
        texts: list[str],
        language: str = "zh",
        disable_data_metrics: bool = False,
    ) -> list[list[SpacyEntity]]:
        """Extract named entities from multiple texts using batch processing.

        Uses nlp.pipe() for efficient batch processing, which is
        significantly faster than processing texts individually.

        Args:
            texts: List of input texts to analyze.
            language: Language code (zh, en, etc.).
            disable_data_metrics: Skip '数据指标' type entities when True.

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
            results.append(self._extract_from_doc(doc, disable_data_metrics))

        log.debug(
            "spacy_batch_extracted",
            language=language,
            text_count=len(texts),
            total_entities=sum(len(r) for r in results),
        )
        return results

    def _extract_from_doc(
        self, doc: object, disable_data_metrics: bool = False
    ) -> list[SpacyEntity]:
        """Extract entities from a spaCy Doc object.

        Args:
            doc: spaCy Doc object.
            disable_data_metrics: Skip '数据指标' type entities when True.

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

            # Skip data metrics entities when configured
            if disable_data_metrics and entity_type == "数据指标":
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
