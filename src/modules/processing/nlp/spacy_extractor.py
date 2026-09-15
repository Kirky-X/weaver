# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Multi-language spaCy NER extractor."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from core.observability import get_logger
from core.utils.paths import CACHE_DIR

log = get_logger(__name__)

MODEL_MAP = {
    # zh_core_web_lg is preferred over zh_core_web_trf because:
    # - trf model requires spacy-transformers + PyTorch/TensorFlow
    # - lg model provides better NER accuracy for production use
    "zh": ["zh_core_web_lg", "zh_core_web_trf"],
    "en": ["en_core_web_lg", "en_core_web_trf"],
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

# Wheels are extracted once into this persistent per-wheel directory and
# reused across restarts, instead of re-extracting on every model load.
WHEEL_EXTRACT_ROOT = CACHE_DIR / "spacy_wheels"


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

    def __init__(
        self,
        zh_model_path: str | None = None,
        en_model_path: str | None = None,
    ) -> None:
        """Initialize SpacyExtractor.

        Args:
            zh_model_path: Path to Chinese model (wheel file or directory).
                          Loaded from configuration file (settings.toml).
            en_model_path: Path to English model (wheel file or directory).
                          Loaded from configuration file (settings.toml).
        """
        self._models: dict[str, object] = {}
        # Loading a model extracts a multi-hundred-MB wheel: serialize the
        # whole check-load-store sequence so concurrent first access loads once.
        self._models_lock = threading.Lock()
        self._temp_dirs: list[str] = []  # Track extracted wheel directories
        # Store model paths from config (priority over env vars)
        self._zh_model_path = zh_model_path
        self._en_model_path = en_model_path

    def cleanup(self) -> None:
        """Clean up temporary directories created during wheel extraction."""
        import shutil

        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._temp_dirs.clear()

    def _extract_wheel_safely(self, wheel_path: str) -> str | None:
        """Extract a wheel file safely with path traversal and size checks.

        Extraction target is a persistent per-wheel directory under
        WHEEL_EXTRACT_ROOT keyed by the wheel filename (unique per
        model+version). The directory is populated in a temp sibling and
        renamed into place atomically, so a partial extraction is never
        reused by a later load or another process.

        Args:
            wheel_path: Path to the .whl file.

        Returns:
            Path to extracted directory, or None if extraction failed.
        """
        import shutil
        import tempfile
        import zipfile

        wheel = Path(wheel_path)

        # Zip bomb protection: check file size. stat() can raise
        # FileNotFoundError/OSError (deleted wheel, permissions) — return
        # None per the method contract instead of propagating to callers.
        try:
            wheel_size = wheel.stat().st_size
        except OSError as e:
            log.warning(
                "spacy_wheel_stat_failed",
                wheel_path=wheel_path,
                error=str(e),
                exc_type=type(e).__name__,
            )
            return None
        if wheel_size > MAX_WHEEL_SIZE:
            log.warning(
                "spacy_wheel_size_exceeded",
                wheel_path=wheel_path,
                size=wheel_size,
                max_size=MAX_WHEEL_SIZE,
            )
            return None

        try:
            WHEEL_EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning(
                "spacy_wheel_cache_dir_unavailable",
                path=str(WHEEL_EXTRACT_ROOT),
                error=str(e),
            )
            return None

        final_dir = WHEEL_EXTRACT_ROOT / wheel.stem
        if final_dir.is_dir() and any(final_dir.iterdir()):
            return str(final_dir)

        # Temp dir must live on the same volume as final_dir for atomic rename
        try:
            extract_dir = tempfile.mkdtemp(prefix="spacy_model_", dir=str(WHEEL_EXTRACT_ROOT))
        except OSError as e:
            log.warning(
                "spacy_temp_dir_creation_failed",
                wheel_path=wheel_path,
                error=str(e),
                exc_type=type(e).__name__,
            )
            return None
        extract_path = Path(extract_dir)
        self._temp_dirs.append(extract_dir)

        try:
            with zipfile.ZipFile(wheel_path, "r") as zf:
                # Path traversal protection: verify all members resolve within extract_dir
                for member in zf.namelist():
                    member_path = (extract_path / member).resolve()
                    if not member_path.is_relative_to(extract_path.resolve()):
                        log.warning(
                            "spacy_wheel_path_traversal",
                            wheel_path=wheel_path,
                            malicious_member=member,
                        )
                        shutil.rmtree(extract_dir, ignore_errors=True)
                        return None

                # Safe to extract
                zf.extractall(extract_dir)

            try:
                os.replace(extract_dir, str(final_dir))
            except OSError:
                # Another process finished extracting the same wheel first;
                # reuse its copy if it is complete, otherwise surface the error.
                shutil.rmtree(extract_dir, ignore_errors=True)
                if final_dir.is_dir() and any(final_dir.iterdir()):
                    return str(final_dir)
                raise

            if extract_dir in self._temp_dirs:
                self._temp_dirs.remove(extract_dir)
            return str(final_dir)

        except (zipfile.BadZipFile, OSError) as e:
            log.warning("spacy_wheel_extract_failed", wheel_path=wheel_path, error=str(e))
            shutil.rmtree(extract_dir, ignore_errors=True)
            # Drop the failed dir from the tracking list so repeated failed
            # extractions do not grow it unboundedly.
            if extract_dir in self._temp_dirs:
                self._temp_dirs.remove(extract_dir)
            return None

    def _load(self, model_name: str) -> object | None:
        """Load a spaCy model (cached).

        Supports loading from:
        1. Config path (zh_model_path or en_model_path from settings.toml)
        2. Local model directory (already extracted)
        3. Installed spaCy model name

        Args:
            model_name: Name of the spaCy model to load.

        Returns:
            Loaded spaCy NLP pipeline or None if loading fails.
        """
        import spacy

        # Get model path from config
        config_path: str | None = None

        if model_name.startswith("zh_core_web"):
            config_path = self._zh_model_path
        elif model_name.startswith("en_core_web"):
            config_path = self._en_model_path

        # Use config path if available
        if config_path:
            path = Path(config_path)
            if path.exists():
                # Case 1: .whl file - extract and load
                if path.suffix == ".whl" and path.is_file():
                    extract_dir = self._extract_wheel_safely(config_path)
                    if extract_dir:
                        # Find the model directory inside extracted wheel
                        # Wheel contains:
                        # - {model_name}.dist-info/ (metadata, NOT the model)
                        # - {model_prefix}/ (actual model directory)
                        # We need to find the actual model directory, not dist-info
                        model_prefix = model_name.split("-")[0]
                        for name in os.listdir(extract_dir):
                            # Skip dist-info directories - they're metadata, not the model
                            if ".dist-info" in name:
                                continue
                            # Check if this is the package directory (e.g., zh_core_web_lg)
                            if name == model_prefix:
                                pkg_dir = os.path.join(extract_dir, name)
                                if os.path.isdir(pkg_dir):
                                    # Wheel structure: pkg_dir/version_dir/ contains actual model
                                    # e.g., zh_core_web_lg/zh_core_web_lg-3.8.0/config.cfg
                                    for subname in os.listdir(pkg_dir):
                                        # Skip non-directories and license files
                                        if not os.path.isdir(os.path.join(pkg_dir, subname)):
                                            continue
                                        if subname in ("LICENSE", "LICENSES_SOURCES"):
                                            continue
                                        # Version directory: zh_core_web_lg-3.8.0
                                        if subname == model_name or subname.startswith(
                                            f"{model_prefix}-"
                                        ):
                                            model_dir = os.path.join(pkg_dir, subname)
                                            # Verify it's a valid spacy model
                                            cfg_path = os.path.join(model_dir, "config.cfg")
                                            if os.path.exists(cfg_path):
                                                nlp = spacy.load(
                                                    model_dir,
                                                    exclude=[
                                                        "parser",
                                                        "tagger",
                                                        "lemmatizer",
                                                    ],
                                                )
                                                log.info(
                                                    "spacy_model_loaded_from_wheel",
                                                    wheel_path=config_path,
                                                    extracted_to=model_dir,
                                                )
                                                return nlp
                            # Also handle flat structure (model dir at root)
                            elif name == model_name or name.startswith(f"{model_prefix}-"):
                                model_dir = os.path.join(extract_dir, name)
                                if os.path.isdir(model_dir):
                                    cfg_path = os.path.join(model_dir, "config.cfg")
                                    if os.path.exists(cfg_path):
                                        nlp = spacy.load(
                                            model_dir,
                                            exclude=[
                                                "parser",
                                                "tagger",
                                                "lemmatizer",
                                            ],
                                        )
                                        log.info(
                                            "spacy_model_loaded_from_wheel",
                                            wheel_path=config_path,
                                            extracted_to=model_dir,
                                        )
                                        return nlp

                        log.warning(
                            "spacy_wheel_extract_no_model_dir",
                            wheel_path=config_path,
                            expected=model_prefix,
                            contents=os.listdir(extract_dir),
                        )

                # Case 2: Directory - load directly
                elif path.is_dir():
                    try:
                        nlp = spacy.load(
                            config_path,
                            exclude=["parser", "tagger", "lemmatizer"],
                        )
                        log.info("spacy_model_loaded_from_local", path=config_path)
                        return nlp
                    except (OSError, ValueError, ImportError) as e:
                        log.info(
                            "spacy_local_load_skipped",
                            path=config_path,
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
        Loaded models are cached per model name for the extractor's
        lifetime; loading is serialized to avoid duplicate work.

        Args:
            language: Language code (zh, en, etc.).

        Returns:
            Loaded spaCy NLP pipeline.

        Raises:
            RuntimeError: If no models could be loaded for the language.
        """
        model_candidates = MODEL_MAP.get(language, MODEL_MAP["default"])

        with self._models_lock:
            for model in model_candidates:
                cached = self._models.get(model)
                if cached is not None:
                    return cached
                nlp = self._load(model)
                if nlp is not None:
                    self._models[model] = nlp
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
