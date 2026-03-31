# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline configuration management.

This module provides external configuration for the news processing pipeline,
allowing node definitions and processing parameters to be managed via YAML files
without modifying code.

Configuration file format (pipeline_config.yaml):

    pipeline:
      version: "1.0"
      phase1:
        concurrency: 5
        stages:
          - name: classifier
            class: modules.processing.pipeline.nodes.classifier.ClassifierNode
            enabled: true
            timeout: 30
          - name: cleaner
            class: modules.processing.pipeline.nodes.cleaner.CleanerNode
            enabled: true
            timeout: 60
          - name: categorizer
            class: modules.processing.pipeline.nodes.categorizer.CategorizerNode
            enabled: true
            timeout: 45
          - name: vectorize
            class: modules.processing.pipeline.nodes.vectorize.VectorizeNode
            enabled: true
            timeout: 120

      phase3:
        concurrency: 5
        stages:
          - name: re_vectorize
            class: modules.processing.pipeline.nodes.re_vectorize.ReVectorizeNode
            enabled: true
            timeout: 120
          - name: analyze
            class: modules.processing.pipeline.nodes.analyze.AnalyzeNode
            enabled: true
            timeout: 90
          - name: quality_scorer
            class: modules.processing.pipeline.nodes.quality_scorer.QualityScorerNode
            enabled: true
            timeout: 60
          - name: credibility
            class: modules.processing.pipeline.nodes.credibility_checker.CredibilityCheckerNode
            enabled: true
            timeout: 45
          - name: entity_extractor
            class: modules.processing.pipeline.nodes.entity_extractor.EntityExtractorNode
            enabled: true
            timeout: 120

      batch:
        merger_class: modules.processing.pipeline.nodes.batch_merger.BatchMergerNode
        enabled: true
        timeout: 180

Usage:
    from modules.processing.pipeline.config import PipelineConfig, PipelineConfigLoader

    # Load from file
    loader = PipelineConfigLoader()
    config = loader.load_from_file("config/pipeline.yaml")

    # Load from directory (auto-discovers *.yaml files)
    configs = loader.load_from_directory("config/pipeline.d/")

    # Create pipeline with config
    pipeline = Pipeline.from_config(llm, config, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.observability.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path as PathType

log = get_logger("pipeline_config")


@dataclass
class StageConfig:
    """Configuration for a single pipeline stage."""

    name: str
    class_path: str
    enabled: bool = True
    timeout: int = 60
    retry: int = 3
    retry_delay: int = 5
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseConfig:
    """Configuration for a pipeline phase."""

    concurrency: int = 5
    stages: list[StageConfig] = field(default_factory=list)

    @property
    def enabled_stages(self) -> list[StageConfig]:
        """Get only enabled stages."""
        return [s for s in self.stages if s.enabled]


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    merger_class: str = "modules.processing.pipeline.nodes.batch_merger.BatchMergerNode"
    enabled: bool = True
    timeout: int = 180


@dataclass
class PipelineConfig:
    """Complete pipeline configuration."""

    version: str = "1.0"
    phase1: PhaseConfig = field(default_factory=PhaseConfig)
    phase3: PhaseConfig = field(default_factory=PhaseConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)

    @classmethod
    def default(cls) -> PipelineConfig:
        """Create default pipeline configuration.

        This matches the hardcoded defaults in graph.py for backward compatibility.
        """
        phase1 = PhaseConfig(
            concurrency=5,
            stages=[
                StageConfig(
                    name="classifier",
                    class_path="modules.processing.pipeline.nodes.classifier.ClassifierNode",
                ),
                StageConfig(
                    name="cleaner",
                    class_path="modules.processing.pipeline.nodes.cleaner.CleanerNode",
                ),
                StageConfig(
                    name="categorizer",
                    class_path="modules.processing.pipeline.nodes.categorizer.CategorizerNode",
                ),
                StageConfig(
                    name="vectorize",
                    class_path="modules.processing.pipeline.nodes.vectorize.VectorizeNode",
                ),
            ],
        )
        phase3 = PhaseConfig(
            concurrency=5,
            stages=[
                StageConfig(
                    name="re_vectorize",
                    class_path="modules.processing.pipeline.nodes.re_vectorize.ReVectorizeNode",
                ),
                StageConfig(
                    name="analyze",
                    class_path="modules.processing.pipeline.nodes.analyze.AnalyzeNode",
                ),
                StageConfig(
                    name="quality_scorer",
                    class_path="modules.processing.pipeline.nodes.quality_scorer.QualityScorerNode",
                ),
                StageConfig(
                    name="credibility",
                    class_path="modules.processing.pipeline.nodes.credibility_checker.CredibilityCheckerNode",
                ),
                StageConfig(
                    name="entity_extractor",
                    class_path="modules.processing.pipeline.nodes.entity_extractor.EntityExtractorNode",
                ),
            ],
        )
        batch = BatchConfig()
        return cls(version="1.0", phase1=phase1, phase3=phase3, batch=batch)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "pipeline": {
                "version": self.version,
                "phase1": {
                    "concurrency": self.phase1.concurrency,
                    "stages": [
                        {
                            "name": s.name,
                            "class": s.class_path,
                            "enabled": s.enabled,
                            "timeout": s.timeout,
                            "retry": s.retry,
                            "retry_delay": s.retry_delay,
                            **s.params,
                        }
                        for s in self.phase1.stages
                    ],
                },
                "phase3": {
                    "concurrency": self.phase3.concurrency,
                    "stages": [
                        {
                            "name": s.name,
                            "class": s.class_path,
                            "enabled": s.enabled,
                            "timeout": s.timeout,
                            "retry": s.retry,
                            "retry_delay": s.retry_delay,
                            **s.params,
                        }
                        for s in self.phase3.stages
                    ],
                },
                "batch": {
                    "merger_class": self.batch.merger_class,
                    "enabled": self.batch.enabled,
                    "timeout": self.batch.timeout,
                },
            }
        }


def _dict_to_stage(data: dict[str, Any]) -> StageConfig:
    """Convert dictionary to StageConfig."""
    return StageConfig(
        name=data.get("name", ""),
        class_path=data.get("class", ""),
        enabled=data.get("enabled", True),
        timeout=data.get("timeout", 60),
        retry=data.get("retry", 3),
        retry_delay=data.get("retry_delay", 5),
        params={
            k: v
            for k, v in data.items()
            if k not in ("name", "class", "enabled", "timeout", "retry", "retry_delay")
        },
    )


def _dict_to_phase(data: dict[str, Any]) -> PhaseConfig:
    """Convert dictionary to PhaseConfig."""
    return PhaseConfig(
        concurrency=data.get("concurrency", 5),
        stages=[_dict_to_stage(s) for s in data.get("stages", [])],
    )


def _dict_to_batch(data: dict[str, Any]) -> BatchConfig:
    """Convert dictionary to BatchConfig."""
    return BatchConfig(
        merger_class=data.get(
            "merger_class", "modules.processing.pipeline.nodes.batch_merger.BatchMergerNode"
        ),
        enabled=data.get("enabled", True),
        timeout=data.get("timeout", 180),
    )


def dict_to_config(data: dict[str, Any]) -> PipelineConfig:
    """Convert dictionary to PipelineConfig."""
    pipeline_data = data.get("pipeline", {})
    return PipelineConfig(
        version=pipeline_data.get("version", "1.0"),
        phase1=_dict_to_phase(pipeline_data.get("phase1", {})),
        phase3=_dict_to_phase(pipeline_data.get("phase3", {})),
        batch=_dict_to_batch(pipeline_data.get("batch", {})),
    )


class PipelineConfigLoader:
    """Loader for pipeline configuration files.

    Supports:
    - YAML files
    - Directory-based configuration (auto-discovers *.yaml)
    - Environment variable overrides
    - Configuration merging
    """

    def __init__(self) -> None:
        self._config_cache: dict[str, PipelineConfig] = {}

    def load_from_file(self, path: str | PathType) -> PipelineConfig:
        """Load configuration from a YAML file.

        Args:
            path: Path to the configuration file.

        Returns:
            Loaded PipelineConfig instance.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config file is invalid.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Pipeline config file not found: {path}")

        log.info("loading_pipeline_config", path=str(path))
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            log.warning("empty_config_file", path=str(path))
            return PipelineConfig.default()

        config = dict_to_config(data)
        self._config_cache[str(path)] = config
        log.info("pipeline_config_loaded", path=str(path), version=config.version)
        return config

    def load_from_directory(self, directory: str | PathType) -> list[PipelineConfig]:
        """Load and merge all YAML configurations from a directory.

        Files are processed in alphabetical order, with later files
        overriding earlier ones.

        Args:
            directory: Path to the configuration directory.

        Returns:
            List of loaded configurations (one per file).

        Raises:
            NotADirectoryError: If directory doesn't exist.
        """
        directory = Path(directory)
        if not directory.exists() or not directory.is_dir():
            raise NotADirectoryError(f"Pipeline config directory not found: {directory}")

        config_files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
        if not config_files:
            log.warning("no_config_files_found", directory=str(directory))
            return []

        configs = []
        for config_file in config_files:
            try:
                config = self.load_from_file(config_file)
                configs.append(config)
                log.info(
                    "config_file_loaded", file=str(config_file), stages=len(config.phase1.stages)
                )
            except Exception as exc:
                log.error("config_file_load_failed", file=str(config_file), error=str(exc))

        return configs

    def load_with_env_override(
        self,
        base_path: str | PathType | None = None,
    ) -> PipelineConfig:
        """Load configuration with environment variable overrides.

        Environment variables:
        - WEAVER_PIPELINE_CONFIG: Path to config file
        - WEAVER_PHASE1_CONCURRENCY: Override phase1 concurrency
        - WEAVER_PHASE3_CONCURRENCY: Override phase3 concurrency

        Args:
            base_path: Base configuration path. Defaults to WEAVER_PIPELINE_CONFIG.

        Returns:
            Configuration with applied overrides.
        """
        import os

        config_path = os.environ.get("WEAVER_PIPELINE_CONFIG", base_path)
        if config_path:
            config = self.load_from_file(config_path)
        else:
            config = PipelineConfig.default()

        # Apply environment overrides
        phase1_concurrency = os.environ.get("WEAVER_PHASE1_CONCURRENCY")
        if phase1_concurrency:
            config.phase1.concurrency = int(phase1_concurrency)

        phase3_concurrency = os.environ.get("WEAVER_PHASE3_CONCURRENCY")
        if phase3_concurrency:
            config.phase3.concurrency = int(phase3_concurrency)

        log.info(
            "config_loaded_with_env_override",
            phase1_concurrency=config.phase1.concurrency,
            phase3_concurrency=config.phase3.concurrency,
        )
        return config


def save_default_config(path: str | PathType = "config/pipeline.yaml") -> None:
    """Save the default pipeline configuration to a file.

    Args:
        path: Destination path for the config file.
    """
    config = PipelineConfig.default()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            config.to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    log.info("default_config_saved", path=str(path))
