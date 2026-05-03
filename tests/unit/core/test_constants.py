# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for core/constants.py enum from_str() methods."""

from __future__ import annotations

import pytest

from core.constants import (
    CacheStrategy,
    DatabaseType,
    EmbeddingModel,
    GraphHealthStatus,
    HealthCheckStatus,
    HealthStatus,
    LLMProvider,
    LLMRole,
    MigrationStatus,
    PipelineTaskStatus,
    ProcessingStatus,
    RelationType,
    ResponseStatus,
    SearchMode,
    SentimentType,
    SortOrder,
    SourceType,
    TaskStatus,
    TiktokenEncoding,
)
from core.llm.types import RoutingMode


class TestDatabaseType:
    """Tests for DatabaseType enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert DatabaseType.from_str("postgres") == DatabaseType.POSTGRES
        assert DatabaseType.from_str("duckdb") == DatabaseType.DUCKDB
        assert DatabaseType.from_str("neo4j") == DatabaseType.NEO4J
        assert DatabaseType.from_str("ladybug") == DatabaseType.LADYBUG
        assert DatabaseType.from_str("redis") == DatabaseType.REDIS

    def test_from_str_case_insensitive(self) -> None:
        """Test from_str handles case correctly."""
        assert DatabaseType.from_str("POSTGRES") == DatabaseType.POSTGRES
        assert DatabaseType.from_str("Ladybug") == DatabaseType.LADYBUG

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid database type"):
            DatabaseType.from_str("invalid_db")

    def test_value_matches_string(self) -> None:
        """Test enum .value matches expected string."""
        assert DatabaseType.POSTGRES.value == "postgres"
        assert DatabaseType.LADYBUG.value == "ladybug"


class TestProcessingStatus:
    """Tests for ProcessingStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert ProcessingStatus.from_str("pending") == ProcessingStatus.PENDING
        assert ProcessingStatus.from_str("processing") == ProcessingStatus.PROCESSING
        assert ProcessingStatus.from_str("completed") == ProcessingStatus.COMPLETED
        assert ProcessingStatus.from_str("failed") == ProcessingStatus.FAILED
        assert ProcessingStatus.from_str("retry") == ProcessingStatus.RETRY

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid processing status"):
            ProcessingStatus.from_str("unknown")


class TestMigrationStatus:
    """Tests for MigrationStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert MigrationStatus.from_str("pending") == MigrationStatus.PENDING
        assert MigrationStatus.from_str("running") == MigrationStatus.RUNNING
        assert MigrationStatus.from_str("completed") == MigrationStatus.COMPLETED
        assert MigrationStatus.from_str("failed") == MigrationStatus.FAILED
        assert MigrationStatus.from_str("cancelled") == MigrationStatus.CANCELLED

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid migration status"):
            MigrationStatus.from_str("unknown")


class TestRoutingMode:
    """Tests for RoutingMode enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert RoutingMode.from_str("auto") == RoutingMode.AUTO
        assert RoutingMode.from_str("fast") == RoutingMode.FAST
        assert RoutingMode.from_str("best") == RoutingMode.BEST

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid routing mode"):
            RoutingMode.from_str("unknown")


class TestSearchMode:
    """Tests for SearchMode enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert SearchMode.from_str("local") == SearchMode.LOCAL
        assert SearchMode.from_str("global") == SearchMode.GLOBAL
        assert SearchMode.from_str("hybrid") == SearchMode.HYBRID
        assert SearchMode.from_str("articles") == SearchMode.ARTICLES

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid search mode"):
            SearchMode.from_str("unknown")


class TestGraphHealthStatus:
    """Tests for GraphHealthStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert GraphHealthStatus.from_str("healthy") == GraphHealthStatus.HEALTHY
        assert GraphHealthStatus.from_str("moderate") == GraphHealthStatus.MODERATE
        assert GraphHealthStatus.from_str("degraded") == GraphHealthStatus.DEGRADED
        assert GraphHealthStatus.from_str("critical") == GraphHealthStatus.CRITICAL

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid graph health status"):
            GraphHealthStatus.from_str("unknown")


class TestResponseStatus:
    """Tests for ResponseStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert ResponseStatus.from_str("success") == ResponseStatus.SUCCESS
        assert ResponseStatus.from_str("error") == ResponseStatus.ERROR
        assert ResponseStatus.from_str("partial") == ResponseStatus.PARTIAL

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid response status"):
            ResponseStatus.from_str("unknown")


class TestHealthCheckStatus:
    """Tests for HealthCheckStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert HealthCheckStatus.from_str("ok") == HealthCheckStatus.OK
        assert HealthCheckStatus.from_str("timeout") == HealthCheckStatus.TIMEOUT
        assert HealthCheckStatus.from_str("error") == HealthCheckStatus.ERROR
        assert HealthCheckStatus.from_str("unavailable") == HealthCheckStatus.UNAVAILABLE

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid health check status"):
            HealthCheckStatus.from_str("unknown")


class TestSortOrder:
    """Tests for SortOrder enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert SortOrder.from_str("asc") == SortOrder.ASC
        assert SortOrder.from_str("desc") == SortOrder.DESC

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid sort order"):
            SortOrder.from_str("unknown")


class TestSourceType:
    """Tests for SourceType enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert SourceType.from_str("rss") == SourceType.RSS
        assert SourceType.from_str("atom") == SourceType.ATOM
        assert SourceType.from_str("html") == SourceType.HTML
        assert SourceType.from_str("json") == SourceType.JSON

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid source type"):
            SourceType.from_str("unknown")


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert HealthStatus.from_str("healthy") == HealthStatus.HEALTHY
        assert HealthStatus.from_str("degraded") == HealthStatus.DEGRADED
        assert HealthStatus.from_str("unhealthy") == HealthStatus.UNHEALTHY

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid health status"):
            HealthStatus.from_str("unknown")


class TestLLMProvider:
    """Tests for LLMProvider enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert LLMProvider.from_str("openai") == LLMProvider.OPENAI
        assert LLMProvider.from_str("anthropic") == LLMProvider.ANTHROPIC
        assert LLMProvider.from_str("azure") == LLMProvider.AZURE
        assert LLMProvider.from_str("local") == LLMProvider.LOCAL
        assert LLMProvider.from_str("zhipu") == LLMProvider.ZHIPU
        assert LLMProvider.from_str("ollama") == LLMProvider.OLLAMA

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid LLM provider"):
            LLMProvider.from_str("unknown")


class TestSentimentType:
    """Tests for SentimentType enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert SentimentType.from_str("positive") == SentimentType.POSITIVE
        assert SentimentType.from_str("negative") == SentimentType.NEGATIVE
        assert SentimentType.from_str("neutral") == SentimentType.NEUTRAL
        assert SentimentType.from_str("mixed") == SentimentType.MIXED

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid sentiment type"):
            SentimentType.from_str("unknown")


class TestPipelineTaskStatus:
    """Tests for PipelineTaskStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert PipelineTaskStatus.from_str("queued") == PipelineTaskStatus.QUEUED
        assert PipelineTaskStatus.from_str("running") == PipelineTaskStatus.RUNNING
        assert PipelineTaskStatus.from_str("paused") == PipelineTaskStatus.PAUSED
        assert PipelineTaskStatus.from_str("completed") == PipelineTaskStatus.COMPLETED
        assert PipelineTaskStatus.from_str("cancelled") == PipelineTaskStatus.CANCELLED
        assert PipelineTaskStatus.from_str("failed") == PipelineTaskStatus.FAILED

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid pipeline task status"):
            PipelineTaskStatus.from_str("unknown")


class TestRelationType:
    """Tests for RelationType enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values (uppercase)."""
        assert RelationType.from_str("RELATED_TO") == RelationType.RELATED_TO
        assert RelationType.from_str("HAS_ENTITY") == RelationType.HAS_ENTITY
        assert RelationType.from_str("REPORTS_ON") == RelationType.REPORTS_ON
        assert RelationType.from_str("MENTIONS") == RelationType.MENTIONS

    def test_from_str_case_insensitive(self) -> None:
        """Test from_str handles lowercase input."""
        assert RelationType.from_str("related_to") == RelationType.RELATED_TO

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid relation type"):
            RelationType.from_str("UNKNOWN")


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert TaskStatus.from_str("running") == TaskStatus.RUNNING
        assert TaskStatus.from_str("done") == TaskStatus.DONE
        assert TaskStatus.from_str("cancelled") == TaskStatus.CANCELLED
        assert TaskStatus.from_str("failed") == TaskStatus.FAILED
        assert TaskStatus.from_str("not_found") == TaskStatus.NOT_FOUND

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid task status"):
            TaskStatus.from_str("unknown")


class TestCacheStrategy:
    """Tests for CacheStrategy enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert CacheStrategy.from_str("redis") == CacheStrategy.REDIS
        assert CacheStrategy.from_str("cashews") == CacheStrategy.CASHUEWS
        assert CacheStrategy.from_str("hybrid") == CacheStrategy.HYBRID

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid cache strategy"):
            CacheStrategy.from_str("unknown")


class TestLLMRole:
    """Tests for LLMRole enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert LLMRole.from_str("primary") == LLMRole.PRIMARY
        assert LLMRole.from_str("secondary") == LLMRole.SECONDARY
        assert LLMRole.from_str("embedding") == LLMRole.EMBEDDING

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid LLM role"):
            LLMRole.from_str("unknown")


class TestEmbeddingModel:
    """Tests for EmbeddingModel enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert EmbeddingModel.from_str("Qwen3-Embedding-0.6B") == EmbeddingModel.DEFAULT

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid embedding model"):
            EmbeddingModel.from_str("unknown")


class TestTiktokenEncoding:
    """Tests for TiktokenEncoding enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert TiktokenEncoding.from_str("cl100k_base") == TiktokenEncoding.CL100K_BASE

    def test_from_str_invalid_raises(self) -> None:
        """Test from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid tiktoken encoding"):
            TiktokenEncoding.from_str("unknown")
