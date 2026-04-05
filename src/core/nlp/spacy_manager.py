# Copyright (c) 2026 KirkyX. All Rights Reserved
"""spaCy model detection and installation manager.

Provides startup-time model validation and automatic installation capabilities.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.observability.logging import get_logger

log = get_logger("spacy_manager")


@dataclass
class SpacyModelConfig:
    """Configuration for spaCy model management.

    Attributes:
        force_install: Automatically install missing models at startup.
        strict_mode: Raise error on installation failure (only when force_install=true).
        models: List of spaCy models to check/install, in priority order.
        local_paths: Mapping of model name to local wheel file path.
    """

    force_install: bool = False
    strict_mode: bool = True
    models: list[str] = field(default_factory=lambda: ["zh_core_web_lg", "en_core_web_sm"])
    local_paths: dict[str, str] = field(default_factory=dict)


class SpacyModelManager:
    """Manages spaCy model detection and installation.

    Detects missing models at startup and optionally installs them.
    Supports both network download and local wheel file installation.
    """

    def __init__(self, config: SpacyModelConfig) -> None:
        """Initialize the manager with configuration.

        Args:
            config: Model management configuration.
        """
        self._config = config

    def check_and_install(self) -> None:
        """Check for missing models and install them if configured.

        This is a blocking operation that runs serially.

        Raises:
            RuntimeError: If strict_mode=True and installation fails.
        """
        missing = self._detect_missing_models()

        if not missing:
            log.info("spacy_models_all_present", models=self._config.models)
            return

        if not self._config.force_install:
            log.warning(
                "spacy_models_missing",
                models=missing,
                hint="Set spacy.force_install=true to auto-install",
            )
            return

        # Serial installation of each missing model
        for model in missing:
            self._install_model(model)

    def _detect_missing_models(self) -> list[str]:
        """Detect which configured models are not installed.

        Returns:
            List of missing model names.
        """
        import spacy

        missing: list[str] = []
        for model in self._config.models:
            try:
                spacy.load(model)
                log.debug("spacy_model_found", model=model)
            except OSError:
                missing.append(model)
                log.debug("spacy_model_missing", model=model)

        return missing

    def _install_model(self, model: str) -> None:
        """Install a single spaCy model.

        Priority:
        1. Local wheel file (if configured and exists)
        2. Network download via spacy.cli.download

        Args:
            model: Name of the model to install.

        Raises:
            RuntimeError: If installation fails and strict_mode=True.
        """
        local_path = self._config.local_paths.get(model)

        if local_path and Path(local_path).exists():
            self._install_from_local(model, local_path)
        else:
            self._install_from_network(model)

    def _install_from_local(self, model: str, local_path: str) -> None:
        """Install model from local wheel file using uv.

        Args:
            model: Model name for logging.
            local_path: Path to the wheel file.

        Raises:
            RuntimeError: If installation fails and strict_mode=True.
        """
        import uv

        log.info("spacy_installing_from_local", model=model, path=local_path)

        result = subprocess.run(  # noqa: S603
            [uv.find_uv_bin(), "pip", "install", local_path],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            error = result.stderr or result.stdout
            self._handle_install_failure(model, error)
        else:
            log.info("spacy_model_installed", model=model, source="local")

    def _install_from_network(self, model: str) -> None:
        """Install model by downloading from the internet.

        Uses spaCy's official Python API for downloading.

        Args:
            model: Name of the model to install.

        Raises:
            RuntimeError: If installation fails and strict_mode=True.
        """
        from spacy.cli import download as spacy_download

        log.info("spacy_installing_from_network", model=model)

        try:
            # spacy_download may call sys.exit on failure
            spacy_download(model)
            log.info("spacy_model_installed", model=model, source="network")
        except SystemExit as e:
            # spacy.cli.download calls sys.exit on failure
            self._handle_install_failure(model, f"spacy download exited with code {e.code}")

    def _handle_install_failure(self, model: str, error: str) -> None:
        """Handle installation failure based on strict_mode setting.

        Args:
            model: Model that failed to install.
            error: Error message.

        Raises:
            RuntimeError: If strict_mode=True.
        """
        if self._config.strict_mode:
            raise RuntimeError(f"Failed to install spaCy model '{model}': {error}")
        log.error(
            "spacy_install_failed_non_strict",
            model=model,
            error=error,
            hint="Application will continue but may fail at runtime",
        )
