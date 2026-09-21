# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Pipeline configuration using pydantic-settings for TOML loading."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from core.observability import get_logger
from core.utils.paths import PROJECT_ROOT

log = get_logger("pipeline_config")


class StageConfig(BaseModel):
    """Configuration for a single pipeline stage (name + enabled flag).

    ``extra="forbid"``: TOML stage tables are built with ``StageConfig(**item)``,
    and Pydantic silently drops unknown keys by default — which would hide a
    typo such as ``enableed = false``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    enabled: bool = True


class PhaseConfig(BaseModel):
    """Configuration for a pipeline phase."""

    concurrency: int = 5
    stages: list[StageConfig] = []
    # Phase 3 only: analyze+narrative_schema 合并调用开关。开启后必调
    # chat 从 3 次/篇降为 2 次/篇；回滚只需置 false（无需改代码）。
    # 注意：若 [phase3.stages] 里 narrative_schema 被 enabled=false 关闭，
    # 应同时置本开关为 false，避免合并调用白算 narrative 部分。
    merge_analyze_narrative: bool = False

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


class MonteCarloConfig(BaseModel):
    """Monte Carlo evidence sampling configuration (pipeline.toml [monte_carlo])."""

    enabled: bool = True
    threshold: int = 10000
    sample_size: int = 5
    region_size: int = 2000
    confidence_threshold: float = 0.4


class PipelineSettings(BaseSettings):
    """Pipeline configuration loaded from config/pipeline.toml.

    Consumed at runtime: phase1/phase3 concurrency, per-stage ``enabled``
    flags (the disabled set in Pipeline), monte_carlo settings, and the
    cleaner thresholds. Stage node wiring itself is hard-coded in
    modules.processing.pipeline.graph (no dynamic class loading).

    Environment variables can override any setting using WEAVER_PIPELINE__ prefix.
    Example: WEAVER_PIPELINE__PHASE1__CONCURRENCY=10
    """

    model_config = SettingsConfigDict(
        toml_file=str(PROJECT_ROOT / "config" / "pipeline.toml"),
        env_prefix="WEAVER_PIPELINE__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    version: str = "1.0"
    phase1: PhaseConfig = PhaseConfig()
    phase3: PhaseConfig = PhaseConfig()

    # Cleaner settings
    cleaner_min_body_chars: int = 100
    cleaner_min_title_similarity: float = 0.7

    # Monte Carlo evidence sampling（lifecycle.init_mc_sampler 消费；
    # 缺此字段时 TOML [monte_carlo] 被静默丢弃 → MC 采样永远不生效）
    monte_carlo: MonteCarloConfig = MonteCarloConfig()

    # Content-hash 缓存版本：prompt/输出结构变更时 bump 此值（或用
    # WEAVER_PIPELINE__CONTENT_HASH_VERSION 覆盖），旧快照即刻全部失效，
    # 避免 7 天 TTL 内新旧结果混杂污染 A/B 对比。
    content_hash_version: int = 2
    # Cached content-hash snapshots expire after this many seconds (7 days).
    content_hash_cache_ttl_seconds: int = 604800
    # ConflictDetectorNode similar-article similarity cutoff (recall lever).
    conflict_similarity_threshold: float = 0.7
    # BatchMergerNode entity-merge similarity cutoff (more conservative than
    # entity resolution on purpose: wrong merges are costly to undo).
    merge_similarity_threshold: float = 0.8

    @field_validator("monte_carlo", mode="before")
    @classmethod
    def parse_monte_carlo(cls, v: Any) -> Any:
        """Pass dicts to the BaseModel constructor (TOML section)."""
        if isinstance(v, dict):
            return MonteCarloConfig(**v)
        return v

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
