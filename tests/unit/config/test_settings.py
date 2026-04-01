# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test configuration settings."""

from config.settings import SchedulerSettings


def test_scheduler_settings_has_pipeline_retry_interval() -> None:
    """Test that SchedulerSettings has pipeline_retry_interval_minutes with default value 15."""
    settings = SchedulerSettings()
    assert hasattr(settings, "pipeline_retry_interval_minutes")
    assert settings.pipeline_retry_interval_minutes == 15


def test_scheduler_settings_custom_pipeline_retry_interval() -> None:
    """Test that SchedulerSettings accepts custom pipeline_retry_interval_minutes value."""
    settings = SchedulerSettings(pipeline_retry_interval_minutes=30)
    assert settings.pipeline_retry_interval_minutes == 30
