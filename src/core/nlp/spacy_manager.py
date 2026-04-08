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

        if local_path:
            if Path(local_path).exists():
                log.info(
                    "spacy_local_path_found",
                    model=model,
                    path=local_path,
                )
                self._install_from_local(model, local_path)
            else:
                # Local path configured but doesn't exist - log warning and fallback
                log.warning(
                    "spacy_local_path_not_found",
                    model=model,
                    configured_path=local_path,
                    hint="Falling back to network download",
                )
                self._install_from_network(model)
        else:
            self._install_from_network(model)

    def _install_from_local(self, model: str, local_path: str) -> None:
        """Install model from local wheel file using pip.

        Args:
            model: Model name for logging.
            local_path: Path to the wheel file.

        Raises:
            RuntimeError: If installation fails and strict_mode=True.
        """
        import shutil

        log.info("spacy_installing_from_local", model=model, path=local_path)

        # Verify path is valid (double-check after _install_model check)
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            log.error(
                "spacy_local_load_failed",
                model=model,
                path=local_path,
                error="File does not exist or is not a file",
            )
            # Fall back to network download instead of failing
            log.info("spacy_falling_back_to_network", model=model)
            self._install_from_network(model)
            return

        # Try uv first, fall back to pip
        uv_bin = shutil.which("uv")
        if uv_bin:
            cmd = [uv_bin, "pip", "install", str(path)]
        else:
            pip_bin = shutil.which("pip") or "pip"
            cmd = [pip_bin, "install", str(path)]

        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            error = result.stderr or result.stdout
            log.error(
                "spacy_local_install_failed",
                model=model,
                path=local_path,
                error=error[:500],  # Truncate long errors
            )
            # Fall back to network download on local install failure
            log.info("spacy_falling_back_to_network", model=model)
            try:
                self._install_from_network(model)
            except Exception as net_exc:
                # If both fail, handle the final failure
                self._handle_install_failure(model, f"Local: {error[:200]}, Network: {net_exc}")
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
