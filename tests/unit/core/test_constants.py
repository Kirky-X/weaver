# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for core/constants.py enum from_str() methods."""

from __future__ import annotations

import pytest

from core.constants import (
    DatabaseType,
    EmbeddingModel,
    GraphHealthStatus,
    HealthCheckStatus,
    HealthStatus,
    LanguageCode,
    LLMProvider,
    LLMRole,
    ProcessingStatus,
    ResponseStatus,
    SearchMode,
    SentimentType,
    SourceType,
    Status,
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


class TestStatus:
    """Tests for the unified Status enum (merged task/pipeline/migration)."""

    def test_values_preserved(self) -> None:
        """Every merged member keeps its historical wire value."""
        assert Status.PENDING.value == "pending"
        assert Status.QUEUED.value == "queued"
        assert Status.RUNNING.value == "running"
        assert Status.PAUSED.value == "paused"
        assert Status.COMPLETED.value == "completed"
        assert Status.CANCELLED.value == "cancelled"
        assert Status.FAILED.value == "failed"
        assert Status.NOT_FOUND.value == "not_found"

    def test_done_collapsed_into_completed(self) -> None:
        """The former background-task 'done' is folded into 'completed'."""
        assert not hasattr(Status, "DONE")
        assert Status("completed") == Status.COMPLETED
        with pytest.raises(ValueError):
            Status("done")

    def test_from_str_valid_values(self) -> None:
        assert Status.from_str("queued") == Status.QUEUED
        assert Status.from_str("running") == Status.RUNNING
        assert Status.from_str("completed") == Status.COMPLETED
        assert Status.from_str("not_found") == Status.NOT_FOUND
        assert Status.from_str("Completed") == Status.COMPLETED

    def test_from_str_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            Status.from_str("done")


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
        assert SearchMode.from_str("drift") == SearchMode.DRIFT
        assert SearchMode.from_str("latency") == SearchMode.LATENCY

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


class TestSourceType:
    """Tests for SourceType enum."""

    def test_from_str_valid_values(self) -> None:
        """Test from_str with valid values."""
        assert SourceType.from_str("rss") == SourceType.RSS
        assert SourceType.from_str("atom") == SourceType.ATOM
        assert SourceType.from_str("html") == SourceType.HTML
        assert SourceType.from_str("json") == SourceType.JSON

    def test_from_str_extended_values(self) -> None:
        """Test from_str with new extended values."""
        assert SourceType.from_str("wechat") == SourceType.WECHAT
        assert SourceType.from_str("twitter") == SourceType.TWITTER
        assert SourceType.from_str("telegram") == SourceType.TELEGRAM
        assert SourceType.from_str("pdf") == SourceType.PDF
        assert SourceType.from_str("api") == SourceType.API

    def test_from_str_case_insensitive(self) -> None:
        """Test from_str handles case correctly for extended values."""
        assert SourceType.from_str("WECHAT") == SourceType.WECHAT
        assert SourceType.from_str("Twitter") == SourceType.TWITTER
        assert SourceType.from_str("TELEGRAM") == SourceType.TELEGRAM
        assert SourceType.from_str("PDF") == SourceType.PDF
        assert SourceType.from_str("API") == SourceType.API

    def test_extended_values_match_strings(self) -> None:
        """Test extended enum .value matches expected string."""
        assert SourceType.WECHAT.value == "wechat"
        assert SourceType.TWITTER.value == "twitter"
        assert SourceType.TELEGRAM.value == "telegram"
        assert SourceType.PDF.value == "pdf"
        assert SourceType.API.value == "api"

    def test_total_member_count(self) -> None:
        """Test SourceType has exactly 9 members (4 original + 5 extended)."""
        assert len(SourceType) == 9

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


class TestLanguageCode:
    """Tests for LanguageCode enum and its spaCy-model single source."""

    def test_values_match_historical_literals(self) -> None:
        """Enum values must equal the raw strings previously hard-coded."""
        assert LanguageCode.ZH.value == "zh"
        assert LanguageCode.EN.value == "en"

    def test_from_str(self) -> None:
        assert LanguageCode.from_str("zh") == LanguageCode.ZH
        assert LanguageCode.from_str("EN") == LanguageCode.EN
        with pytest.raises(ValueError, match="Invalid language code"):
            LanguageCode.from_str("fr")

    def test_spacy_model_names_match_old_map(self) -> None:
        """Derived model names must be byte-identical to the pre-refactor maps.

        Guards the single-sourcing refactor: spacy_extractor.MODEL_MAP and
        bm25 SUPPORTED_LANGUAGES used to spell these names literally.
        """
        assert LanguageCode.ZH.spacy_models == ("zh_core_web_lg", "zh_core_web_trf")
        assert LanguageCode.EN.spacy_models == ("en_core_web_lg", "en_core_web_trf")
        assert LanguageCode.ZH.primary_spacy_model == "zh_core_web_lg"

    def test_model_map_and_bm25_supported_languages_preserved(self) -> None:
        """The derived maps equal the exact literals they replaced."""
        from modules.processing.nlp.spacy_extractor import MODEL_MAP

        assert MODEL_MAP == {
            "zh": ["zh_core_web_lg", "zh_core_web_trf"],
            "en": ["en_core_web_lg", "en_core_web_trf"],
            "default": ["xx_ent_wiki_sm"],
        }

        from modules.knowledge.search.retrievers.bm25_retriever import BM25Retriever

        assert BM25Retriever.SUPPORTED_LANGUAGES == {
            "zh": "zh_core_web_lg",
            "en": "en_core_web_lg",
        }


class TestDatabaseTypeSingleSource:
    """Axis enums must keep their historical string values after sourcing
    member values from core.constants.DatabaseType (P1 de-duplication)."""

    def test_relational_axis_values_unchanged(self) -> None:
        from core.db.query_builders import DatabaseType as RelationalDatabaseType

        assert RelationalDatabaseType.POSTGRES.value == "postgres"
        assert RelationalDatabaseType.DUCKDB.value == "duckdb"
        # str-subclass equality with the literal is preserved
        assert RelationalDatabaseType.POSTGRES == "postgres"

    def test_graph_axis_values_unchanged(self) -> None:
        from core.db.graph_query_builders import GraphDatabaseType

        assert GraphDatabaseType.NEO4J.value == "neo4j"
        assert GraphDatabaseType.LADYBUG.value == "ladybug"

    def test_axis_values_match_canonical(self) -> None:
        from core.constants import DatabaseType as Canonical
        from core.db.graph_query_builders import GraphDatabaseType
        from core.db.query_builders import DatabaseType as RelationalDatabaseType

        assert RelationalDatabaseType.POSTGRES.value == Canonical.POSTGRES.value
        assert RelationalDatabaseType.DUCKDB.value == Canonical.DUCKDB.value
        assert GraphDatabaseType.NEO4J.value == Canonical.NEO4J.value
        assert GraphDatabaseType.LADYBUG.value == Canonical.LADYBUG.value
