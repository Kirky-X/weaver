# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for FakeNewsDetector / SimHash dedup settings wiring.

Verifies that ``settings.fake_news_detector`` and ``settings.dedup`` are
real switches: values flow from TOML/env through Settings into
``FakeNewsDetectorConfig.from_settings`` and the container's SimHash
deduplicator (previously both were constructed with hardcoded defaults,
making the configuration a no-op).
"""

from __future__ import annotations

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
