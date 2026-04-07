# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline configuration using pydantic-settings for TOML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from core.observability.logging import get_logger

log = get_logger("pipeline_config")

# Project root for config file paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


class StageConfig(BaseModel):
    """Configuration for a single pipeline stage."""

    name: str = ""
    class_path: str = ""
    enabled: bool = True
    timeout: int = 60
    retry: int = 3
    retry_delay: int = 5
    params: dict[str, Any] = {}


class PhaseConfig(BaseModel):
    """Configuration for a pipeline phase."""

    concurrency: int = 5
    stages: list[StageConfig] = []

    @property
    def enabled_stages(self) -> list[StageConfig]:
        """Get only enabled stages."""
        return [s for s in self.stages if s.enabled]

    @field_validator("stages", mode="before")
    @classmethod
    def parse_stages(cls, v: Any) -> list[StageConfig]:
        """Parse stages from TOML array of tables."""
        if v is None:
            return []
        if isinstance(v, list):
            result: list[StageConfig] = []
            for item in v:
                if isinstance(item, StageConfig):
                    result.append(item)
                elif isinstance(item, dict):
                    result.append(StageConfig(**item))
            return result
        return []


class BatchConfig(BaseModel):
    """Configuration for batch processing."""

    merger_class: str = "modules.processing.pipeline.nodes.batch_merger.BatchMergerNode"
    enabled: bool = True
    timeout: int = 180


class PipelineSettings(BaseSettings):
    """Pipeline configuration loaded from config/pipeline.toml.

    Environment variables can override any setting using WEAVER_PIPELINE__ prefix.
    Example: WEAVER_PIPELINE__PHASE1__CONCURRENCY=10
    """

    model_config = SettingsConfigDict(
        toml_file=str(_PROJECT_ROOT / "config" / "pipeline.toml"),
        env_prefix="WEAVER_PIPELINE__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    version: str = "1.0"
    phase1: PhaseConfig = PhaseConfig()
    phase3: PhaseConfig = PhaseConfig()
    batch: BatchConfig = BatchConfig()

    @field_validator("phase1", "phase3", mode="before")
    @classmethod
    def parse_phase(cls, v: Any) -> PhaseConfig:
        """Parse phase configuration."""
        if v is None:
            return PhaseConfig()
        if isinstance(v, PhaseConfig):
            return v
        if isinstance(v, dict):
            return PhaseConfig(**v)
        return PhaseConfig()

    @field_validator("batch", mode="before")
    @classmethod
    def parse_batch(cls, v: Any) -> BatchConfig:
        """Parse batch configuration."""
        if v is None:
            return BatchConfig()
        if isinstance(v, BatchConfig):
            return v
        if isinstance(v, dict):
            return BatchConfig(**v)
        return BatchConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Configure source priority: env > init > TOML."""
        return (
            env_settings,  # Highest priority: environment variables
            init_settings,  # Programmatic overrides
            TomlConfigSettingsSource(settings_cls),  # TOML file
        )


# Backward compatibility alias
PipelineConfig = PipelineSettings
