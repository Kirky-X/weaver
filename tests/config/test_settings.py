# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for MAGMA configuration settings."""

import pytest

from config.settings import (
    IntentRoutingSettings,
    SearchSettings,
    TemporalInferenceSettings,
)


@pytest.mark.unit
def test_intent_routing_defaults():
    """Test that intent routing settings have correct defaults."""
    settings = IntentRoutingSettings()

    assert settings.enabled is True
    assert settings.classification_threshold == 0.7
    assert settings.fallback_mode == "local"
    assert settings.allow_explicit_mode is True


@pytest.mark.unit
def test_temporal_inference_defaults():
    """Test that temporal inference settings have correct defaults."""
    settings = TemporalInferenceSettings()

    assert settings.enabled is True
    assert settings.default_window_days == 7
    assert settings.parse_chinese_expressions is True
    assert settings.auto_anchor is True


@pytest.mark.unit
def test_intent_routing_custom_values():
    """Test intent routing settings with custom values."""
    settings = IntentRoutingSettings(
        enabled=False,
        classification_threshold=0.5,
        fallback_mode="global",
        allow_explicit_mode=False,
    )
    assert settings.enabled is False
    assert settings.classification_threshold == 0.5
    assert settings.fallback_mode == "global"
    assert settings.allow_explicit_mode is False


@pytest.mark.unit
def test_temporal_inference_custom_values():
    """Test temporal inference settings with custom values."""
    settings = TemporalInferenceSettings(
        enabled=False,
        default_window_days=14,
        parse_chinese_expressions=False,
        auto_anchor=False,
    )
    assert settings.enabled is False
    assert settings.default_window_days == 14
    assert settings.parse_chinese_expressions is False
    assert settings.auto_anchor is False
