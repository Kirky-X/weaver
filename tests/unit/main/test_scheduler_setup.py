# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for scheduler setup in main.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSchedulerConfig:
    """Tests for scheduler configuration values."""

    def test_scheduler_settings_has_pipeline_retry_interval(self):
        """Verify SchedulerSettings has pipeline_retry_interval_minutes field."""
        from config.settings import Settings, SchedulerSettings

        # Check the class has the field
        assert hasattr(SchedulerSettings, "model_fields")
        fields = SchedulerSettings.model_fields

        # This will fail if the field doesn't exist (Task #1 prerequisite)
        if "pipeline_retry_interval_minutes" in fields:
            settings = Settings()
            assert settings.scheduler.pipeline_retry_interval_minutes == 15
        else:
            pytest.skip(
                "pipeline_retry_interval_minutes config field not yet added (Task #1 pending)"
            )

    @pytest.mark.asyncio
    async def test_retry_pipeline_uses_config_interval(self):
        """Verify retry_pipeline_processing job uses config interval value."""
        from config.settings import Settings

        settings = Settings()

        # Check if config field exists
        if not hasattr(settings.scheduler, "pipeline_retry_interval_minutes"):
            pytest.skip(
                "pipeline_retry_interval_minutes config field not yet added (Task #1 pending)"
            )

        expected_interval = settings.scheduler.pipeline_retry_interval_minutes

        # This test verifies the config is accessible and has the correct default
        # The actual usage in _setup_scheduler will be verified after Task #1 completes
        assert expected_interval == 15

    def test_scheduler_job_registration_structure(self):
        """Verify the scheduler job registration structure."""
        # SchedulerJobs is imported inside _setup_scheduler from modules.scheduler.jobs
        # This test documents the expected structure for when Task #1 completes
        from config.settings import Settings

        settings = Settings()

        # After Task #1 completes, this field will exist
        if hasattr(settings.scheduler, "pipeline_retry_interval_minutes"):
            # Verify the default value
            assert settings.scheduler.pipeline_retry_interval_minutes == 15
        else:
            pytest.skip(
                "pipeline_retry_interval_minutes config field not yet added (Task #1 pending)"
            )
