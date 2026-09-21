# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for FakeNewsDetector / SimHash dedup settings wiring.

Verifies that ``settings.fake_news_detector`` and ``settings.dedup`` are
real switches: values flow from TOML/env through Settings into
``FakeNewsDetectorConfig.from_settings`` and the container's SimHash
deduplicator (previously both were constructed with hardcoded defaults,
making the configuration a no-op).
"""

from __future__ import annotations

import pytest

from modules.analytics.fake_news_detector import FakeNewsDetectorConfig
from config.subconfigs import DedupSettings, FakeNewsDetectorSettings


class TestFakeNewsDetectorConfigFromSettings:
    """FakeNewsDetectorConfig.from_settings mapping."""

    def test_default_settings_map_to_defaults(self):
        settings = FakeNewsDetectorSettings()
        config = FakeNewsDetectorConfig.from_settings(settings)

        assert config.trusted_threshold == settings.confidence_trusted
        assert config.fake_threshold == settings.confidence_suspicious
        assert config.exaggeration_words == list(settings.exaggeration_keywords)
        # Empty model_path → rule-based fallback (None)
        assert config.lightgbm_model_path is None

    def test_custom_settings_override_runtime_config(self):
        settings = FakeNewsDetectorSettings(
            confidence_trusted=0.9,
            confidence_suspicious=0.2,
            exaggeration_keywords=["自定义词"],
            model_path="/models/lgbm.txt",
        )
        config = FakeNewsDetectorConfig.from_settings(settings)

        assert config.trusted_threshold == 0.9
        assert config.fake_threshold == 0.2
        assert config.exaggeration_words == ["自定义词"]
        assert config.lightgbm_model_path == "/models/lgbm.txt"

    def test_settings_loaded_from_toml(self):
        """settings.toml [fake_news_detector] and [dedup] sections load."""
        from config.settings import Settings

        settings = Settings()
        assert isinstance(settings.fake_news_detector, FakeNewsDetectorSettings)
        assert settings.fake_news_detector.enabled is True
        assert settings.dedup.enable_simhash_dedup is True
        assert settings.dedup.simhash_hamming_threshold == 3


class TestDedupSettings:
    """DedupSettings defaults mirror the TOML [dedup] section."""

    def test_defaults(self):
        settings = DedupSettings()
        assert settings.enable_simhash_dedup is True
        assert settings.simhash_hamming_threshold == 3


class TestCommunitySimilarityThresholdWiring:
    """settings.search.community_similarity_threshold feeds both builders."""

    def test_settings_field_loaded(self):
        from config.settings import Settings

        settings = Settings()
        assert settings.search.community_similarity_threshold == 0.3

    def test_builder_stores_threshold(self):
        from unittest.mock import MagicMock

        from modules.knowledge.search.context.global_context import GlobalContextBuilder
        from modules.knowledge.search.context.ladybug_global_context import (
            LadybugGlobalContextBuilder,
        )

        ladybug = LadybugGlobalContextBuilder(graph_pool=MagicMock(), similarity_threshold=0.55)
        assert ladybug._similarity_threshold == 0.55

        neo4j = GlobalContextBuilder(graph_pool=MagicMock(), similarity_threshold=0.55)
        assert neo4j._similarity_threshold == 0.55

    def test_container_passes_setting_to_builders(self):
        """Container must forward the setting (regression guard vs hardcode)."""
        import inspect
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src" / "container" / "search.py"
        ).read_text(encoding="utf-8")
        assert source.count("community_similarity_threshold") == 2
        assert "similarity_threshold=self._settings.search.community_similarity_threshold" in source
