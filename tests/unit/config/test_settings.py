# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test configuration settings."""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import APISettings, SchedulerSettings


def test_scheduler_settings_has_pipeline_retry_interval() -> None:
    """Test that SchedulerSettings has pipeline_retry_interval_minutes with default value 15."""
    settings = SchedulerSettings()
    assert hasattr(settings, "pipeline_retry_interval_minutes")
    assert settings.pipeline_retry_interval_minutes == 15


def test_scheduler_settings_custom_pipeline_retry_interval() -> None:
    """Test that SchedulerSettings accepts custom pipeline_retry_interval_minutes value."""
    settings = SchedulerSettings(pipeline_retry_interval_minutes=30)
    assert settings.pipeline_retry_interval_minutes == 30


def test_scheduler_settings_extended_fields():
    """Verify all new scheduler config fields exist with correct defaults."""
    settings = SchedulerSettings()
    # Global
    assert settings.enabled is True
    assert settings.misfire_grace_time_seconds == 300
    assert settings.job_timeout_seconds == 600
    # Data Sync
    assert settings.sync_pending_to_neo4j_interval_minutes == 10
    assert settings.retry_neo4j_writes_interval_minutes == 10
    assert settings.sync_neo4j_with_postgres_interval_hours == 1
    assert settings.consistency_check_cron_hour == 3
    assert settings.consistency_check_cron_minute == 0
    # Pipeline Retry
    assert settings.pipeline_retry_stuck_timeout_minutes == 30
    assert settings.pipeline_retry_max_retries == 3
    # Cleanup
    assert settings.cleanup_old_synced_days == 7
    assert settings.cleanup_old_synced_cron_hour == 3
    assert settings.cleanup_old_synced_cron_minute == 30
    assert settings.llm_failure_cleanup_interval_hours == 24
    assert settings.llm_failure_cleanup_retention_days == 3
    assert settings.llm_usage_raw_cleanup_interval_hours == 6
    assert settings.llm_usage_raw_retention_days == 2
    assert settings.archive_old_neo4j_nodes_cron_day_of_week == "sat"
    assert settings.archive_old_neo4j_nodes_cron_hour == 2
    assert settings.archive_old_neo4j_days == 90
    assert settings.cleanup_orphan_vectors_cron_day_of_week == "sat"
    assert settings.cleanup_orphan_vectors_cron_hour == 3
    # Aggregation
    assert settings.llm_usage_aggregate_interval_minutes == 5
    assert settings.llm_usage_redis_buffer_ttl_seconds == 7200
    # Metrics
    assert settings.persist_status_metrics_interval_minutes == 5
    # Source Scoring
    assert settings.source_auto_score_cron_hour == 3
    # Knowledge Graph
    assert settings.community_check_interval_minutes == 30


class TestAPISettingsPortDetection:
    """Tests for APISettings port auto-detection functionality."""

    def test_api_settings_has_port_auto_detect_field(self) -> None:
        """APISettings should have port_auto_detect field with default True."""
        with patch("core.net.port_finder.PortFinder") as mock_finder:
            mock_finder.is_port_available.return_value = True
            settings = APISettings()
            assert hasattr(settings, "port_auto_detect")
            assert settings.port_auto_detect is True

    def test_api_settings_has_port_max_attempts_field(self) -> None:
        """APISettings should have port_max_attempts field with default 100."""
        with patch("core.net.port_finder.PortFinder") as mock_finder:
            mock_finder.is_port_available.return_value = True
            settings = APISettings()
            assert hasattr(settings, "port_max_attempts")
            assert settings.port_max_attempts == 100

    def test_resolve_port_does_not_change_when_available(self) -> None:
        """Port should remain unchanged when the configured port is available."""
        with (
            patch("core.net.port_finder.PortFinder") as mock_finder,
            patch("core.net.port_announcer.PortAnnouncer") as mock_announcer,
        ):
            mock_finder.is_port_available.return_value = True
            mock_announcer.return_value.announce = MagicMock()

            settings = APISettings(port=8000)

            assert settings.port == 8000
            mock_finder.is_port_available.assert_called_once_with("127.0.0.1", 8000)

    def test_resolve_port_searches_when_unavailable(self) -> None:
        """Port should be updated when the configured port is unavailable."""
        with (
            patch("core.net.port_finder.PortFinder") as mock_finder,
            patch("core.net.port_announcer.PortAnnouncer") as mock_announcer,
        ):
            mock_finder.is_port_available.return_value = False
            mock_finder.find_available_port.return_value = 8005
            mock_announcer.return_value.announce = MagicMock()

            settings = APISettings(port=8000)

            assert settings.port == 8005
            mock_finder.find_available_port.assert_called_once_with(
                host="127.0.0.1",
                start_port=8000,
                max_attempts=100,
            )

    def test_resolve_port_disabled_when_auto_detect_false(self) -> None:
        """Port detection should be skipped when port_auto_detect is False."""
        with patch("core.net.port_finder.PortFinder") as mock_finder:
            # Even if we set up the mock, it should not be called
            settings = APISettings(port=8000, port_auto_detect=False)

            assert settings.port == 8000
            mock_finder.is_port_available.assert_not_called()

    def test_resolve_port_uses_custom_max_attempts(self) -> None:
        """Port search should respect custom port_max_attempts."""
        with (
            patch("core.net.port_finder.PortFinder") as mock_finder,
            patch("core.net.port_announcer.PortAnnouncer") as mock_announcer,
        ):
            mock_finder.is_port_available.return_value = False
            mock_finder.find_available_port.return_value = 8005
            mock_announcer.return_value.announce = MagicMock()

            settings = APISettings(port=8000, port_max_attempts=50)

            mock_finder.find_available_port.assert_called_once_with(
                host="127.0.0.1",
                start_port=8000,
                max_attempts=50,
            )

    def test_resolve_port_raises_on_failure(self) -> None:
        """Should raise exception when port resolution fails."""
        from core.net.errors import PortExhaustionError

        with (
            patch("core.net.port_finder.PortFinder") as mock_finder,
            patch("core.net.port_announcer.PortAnnouncer"),
        ):
            mock_finder.is_port_available.return_value = False
            mock_finder.find_available_port.side_effect = PortExhaustionError(
                "127.0.0.1", 8000, 100
            )

            with pytest.raises(PortExhaustionError):
                APISettings(port=8000)
