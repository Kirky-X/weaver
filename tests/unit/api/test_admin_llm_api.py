# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for admin LLM API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestLLMUsageModels:
    """Tests for LLM usage models."""

    def test_llm_usage_record_model(self) -> None:
        """Test LLMUsageRecord model with all fields."""
        from api.schemas.llm_usage import LLMUsageRecord

        record = LLMUsageRecord(
            time_bucket=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
            label="test-label",
            call_point="entity_extractor",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            call_count=100,
            input_tokens=50000,
            output_tokens=25000,
            total_tokens=75000,
            latency_avg_ms=500.0,
            latency_min_ms=200.0,
            latency_max_ms=1000.0,
            success_count=98,
            failure_count=2,
        )
        assert record.call_count == 100
        assert record.total_tokens == 75000

    def test_llm_usage_response_model(self) -> None:
        """Test LLMUsageResponse model."""
        from api.schemas.llm_usage import LLMUsageRecord, LLMUsageResponse

        record = LLMUsageRecord(
            time_bucket=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
            label="test",
            call_point="extractor",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            call_count=10,
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            latency_avg_ms=300.0,
            latency_min_ms=100.0,
            latency_max_ms=500.0,
            success_count=10,
            failure_count=0,
        )

        response = LLMUsageResponse(records=[record], total=1)
        assert response.total == 1
        assert len(response.records) == 1

    def test_llm_usage_summary_model(self) -> None:
        """Test LLMUsageSummary model."""
        from api.schemas.llm_usage import LLMUsageSummary

        summary = LLMUsageSummary(
            total_calls=1000,
            total_input_tokens=500000,
            total_output_tokens=250000,
            total_tokens=750000,
            avg_latency_ms=450.0,
            success_rate=0.98,
        )
        assert summary.total_calls == 1000
        assert summary.success_rate == 0.98

    def test_llm_usage_by_provider_model(self) -> None:
        """Test LLMUsageByProvider model."""
        from api.schemas.llm_usage import LLMUsageByProvider

        by_provider = LLMUsageByProvider(
            provider="openai",
            call_count=700,
            total_tokens=500000,
        )
        assert by_provider.provider == "openai"
        assert by_provider.call_count == 700

    def test_llm_usage_by_model_model(self) -> None:
        """Test LLMUsageByModel model."""
        from api.schemas.llm_usage import LLMUsageByModel

        by_model = LLMUsageByModel(
            model="gpt-4",
            provider="openai",
            call_count=500,
            total_tokens=350000,
        )
        assert by_model.model == "gpt-4"

    def test_llm_usage_by_call_point_model(self) -> None:
        """Test LLMUsageByCallPoint model."""
        from api.schemas.llm_usage import LLMUsageByCallPoint

        by_call_point = LLMUsageByCallPoint(
            call_point="entity_extractor",
            call_count=400,
            total_tokens=200000,
        )
        assert by_call_point.call_point == "entity_extractor"


class TestAdminRouter:
    """Tests for admin router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.admin import router

        assert router.prefix == "/admin"
