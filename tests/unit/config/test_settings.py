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
