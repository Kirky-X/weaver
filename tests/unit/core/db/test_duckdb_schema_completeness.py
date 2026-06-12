# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DuckDB schema completeness — TDD tests that verify the DuckDB
DDL in core.db.duckdb_schema matches the PostgreSQL ORM models.

These tests parse the raw SQL in SCHEMA_QUERIES / VIEW_QUERIES and assert
that every expected table exists with the correct column set.  They are
meant to FAIL until the DuckDB schema is brought up to date.
"""

from __future__ import annotations

import re

import pytest

from core.db.duckdb_schema import SCHEMA_QUERIES, SEQUENCE_QUERIES

# ── Helpers ──────────────────────────────────────────────────


def parse_tables_from_schema() -> dict[str, set[str]]:
    """Parse SCHEMA_QUERIES to extract {table_name: {col1, col2, ...}}."""
    tables: dict[str, set[str]] = {}
    for query in SCHEMA_QUERIES:
        match = re.search(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*)\)",
            query,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            table_name = match.group(1)
            body = match.group(2)
            columns: set[str] = set()
            for line in body.split(","):
                line = line.strip()
                if not line:
                    continue
                # Skip constraint lines (PRIMARY KEY, UNIQUE, CHECK, FOREIGN, CONSTRAINT)
                # Use word boundary to avoid matching column names starting with "primary_"
                if re.match(
                    r"(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)", line, re.IGNORECASE
                ):
                    continue
                # First word is column name
                col_match = re.match(r"(\w+)\s", line)
                if col_match:
                    columns.add(col_match.group(1).lower())
            tables[table_name] = columns
    return tables


def parse_views_from_module() -> dict[str, set[str]]:
    """Parse VIEW_QUERIES (if exported) to extract {view_name: {col1, col2, ...}}."""
    import core.db.duckdb_schema as mod

    view_queries = getattr(mod, "VIEW_QUERIES", [])
    views: dict[str, set[str]] = {}
    for query in view_queries:
        match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+AS\s+SELECT\s+(.*?)\s+FROM",
            query,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            view_name = match.group(1)
            select_clause = match.group(2)
            columns: set[str] = set()
            for part in select_clause.split(","):
                part = part.strip()
                # Handle "col AS alias" — take the alias
                as_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
                if as_match:
                    columns.add(as_match.group(1).lower())
                else:
                    # Take last dotted component (table.col → col)
                    token = part.split(".")[-1].strip()
                    token = re.match(r"(\w+)", token)
                    if token:
                        columns.add(token.group(1).lower())
            views[view_name] = columns
    return views


def _has_table(tables: dict[str, set[str]], name: str) -> bool:
    return name in tables


# ── Task 1.1 — DuckDB Schema completeness ────────────────────


class TestArticlesCoreTable:
    """articles_core must have exactly 25 columns matching the vertical-split model."""

    EXPECTED_COLUMNS = {
        "id",
        "source_url",
        "source_host",
        "title",
        "category",
        "language",
        "region",
        "score",
        "sentiment_score",
        "credibility_score",
        "persist_status",
        "publish_time",
        "merged_into",
        "is_merged",
        "merged_source_ids",
        "content_hash",
        "version",
        "document_type",
        "doc_metadata",
        "task_id",
        "processing_stage",
        "processing_error",
        "retry_count",
        "created_at",
        "updated_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "articles_core"
        ), "articles_core table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "articles_core"), "articles_core table missing"
        assert (
            col in tables["articles_core"]
        ), f"Column '{col}' missing from articles_core. Got: {sorted(tables['articles_core'])}"

    def test_column_count(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "articles_core"), "articles_core table missing"
        actual = tables["articles_core"]
        assert len(actual) == len(self.EXPECTED_COLUMNS), (
            f"articles_core has {len(actual)} columns, expected {len(self.EXPECTED_COLUMNS)}. "
            f"Extra: {sorted(actual - self.EXPECTED_COLUMNS)}, "
            f"Missing: {sorted(self.EXPECTED_COLUMNS - actual)}"
        )


class TestArticleBodiesTable:
    """article_bodies must have exactly 3 columns."""

    EXPECTED_COLUMNS = {"article_id", "body", "summary"}

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "article_bodies"
        ), "article_bodies table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "article_bodies"), "article_bodies table missing"
        assert (
            col in tables["article_bodies"]
        ), f"Column '{col}' missing from article_bodies. Got: {sorted(tables['article_bodies'])}"

    def test_column_count(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "article_bodies"), "article_bodies table missing"
        actual = tables["article_bodies"]
        assert len(actual) == len(self.EXPECTED_COLUMNS), (
            f"article_bodies has {len(actual)} columns, expected {len(self.EXPECTED_COLUMNS)}. "
            f"Extra: {sorted(actual - self.EXPECTED_COLUMNS)}, "
            f"Missing: {sorted(self.EXPECTED_COLUMNS - actual)}"
        )


class TestArticleAnalysisTable:
    """article_analysis must have exactly 16 columns."""

    EXPECTED_COLUMNS = {
        "article_id",
        "is_news",
        "subjects",
        "key_data",
        "impact",
        "has_data",
        "quality_score",
        "sentiment",
        "primary_emotion",
        "emotion_targets",
        "source_credibility",
        "cross_verification",
        "content_check_score",
        "credibility_flags",
        "verified_by_sources",
        "data_conflicts",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "article_analysis"
        ), "article_analysis table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "article_analysis"), "article_analysis table missing"
        assert col in tables["article_analysis"], (
            f"Column '{col}' missing from article_analysis. "
            f"Got: {sorted(tables['article_analysis'])}"
        )

    def test_column_count(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "article_analysis"), "article_analysis table missing"
        actual = tables["article_analysis"]
        assert len(actual) == len(self.EXPECTED_COLUMNS), (
            f"article_analysis has {len(actual)} columns, expected {len(self.EXPECTED_COLUMNS)}. "
            f"Extra: {sorted(actual - self.EXPECTED_COLUMNS)}, "
            f"Missing: {sorted(self.EXPECTED_COLUMNS - actual)}"
        )


class TestCommunityVectorsTable:
    """community_vectors must exist with metadata columns."""

    EXPECTED_COLUMNS = {
        "community_id",
        "embedding",
        "model_id",
        "title",
        "summary",
        "entity_count",
        "article_count",
        "rank",
        "updated_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "community_vectors"
        ), "community_vectors table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "community_vectors"), "community_vectors table missing"
        assert col in tables["community_vectors"], (
            f"Column '{col}' missing from community_vectors. "
            f"Got: {sorted(tables['community_vectors'])}"
        )


class TestSentimentShiftsTable:
    """sentiment_shifts must exist with detection window columns."""

    EXPECTED_COLUMNS = {
        "id",
        "community_id",
        "community_title",
        "shift_type",
        "direction",
        "magnitude",
        "confidence",
        "detected_at",
        "window_start",
        "window_end",
        "before_avg",
        "after_avg",
        "trigger_article_ids",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "sentiment_shifts"
        ), "sentiment_shifts table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "sentiment_shifts"), "sentiment_shifts table missing"
        assert col in tables["sentiment_shifts"], (
            f"Column '{col}' missing from sentiment_shifts. "
            f"Got: {sorted(tables['sentiment_shifts'])}"
        )


class TestDailyBriefingsTable:
    """daily_briefings must exist with title, summary, status columns."""

    EXPECTED_COLUMNS = {
        "id",
        "briefing_date",
        "title",
        "summary",
        "status",
        "total_items",
        "generated_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "daily_briefings"
        ), "daily_briefings table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "daily_briefings"), "daily_briefings table missing"
        assert (
            col in tables["daily_briefings"]
        ), f"Column '{col}' missing from daily_briefings. Got: {sorted(tables['daily_briefings'])}"


class TestDailyBriefingItemsTable:
    """daily_briefing_items must exist with scoring columns."""

    EXPECTED_COLUMNS = {
        "id",
        "briefing_id",
        "article_id",
        "rank",
        "score",
        "score_breakdown",
        "category",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "daily_briefing_items"), (
            "daily_briefing_items table is missing from SCHEMA_QUERIES. "
            "Found tables: " + ", ".join(sorted(tables))
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "daily_briefing_items"), "daily_briefing_items table missing"
        assert col in tables["daily_briefing_items"], (
            f"Column '{col}' missing from daily_briefing_items. "
            f"Got: {sorted(tables['daily_briefing_items'])}"
        )


class TestApiKeysTable:
    """api_keys must exist with rotation and scope columns."""

    EXPECTED_COLUMNS = {
        "id",
        "key_id",
        "key_hash",
        "scopes",
        "rate_limit_per_min",
        "expires_at",
        "last_used_at",
        "is_revoked",
        "rotated_to",
        "created_by",
        "created_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "api_keys"
        ), "api_keys table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "api_keys"), "api_keys table missing"
        assert (
            col in tables["api_keys"]
        ), f"Column '{col}' missing from api_keys. Got: {sorted(tables['api_keys'])}"


class TestAlertRulesTable:
    """alert_rules must exist with metric/operator check columns."""

    EXPECTED_COLUMNS = {
        "id",
        "entity_name",
        "metric",
        "operator",
        "threshold",
        "channel",
        "cooldown_minutes",
        "enabled",
        "created_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "alert_rules"
        ), "alert_rules table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "alert_rules"), "alert_rules table missing"
        assert (
            col in tables["alert_rules"]
        ), f"Column '{col}' missing from alert_rules. Got: {sorted(tables['alert_rules'])}"


class TestAlertEventsTable:
    """alert_events must exist with trigger and acknowledgement columns."""

    EXPECTED_COLUMNS = {
        "id",
        "rule_id",
        "entity_name",
        "metric_value",
        "triggered_at",
        "acknowledged_at",
        "detail",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "alert_events"
        ), "alert_events table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "alert_events"), "alert_events table missing"
        assert (
            col in tables["alert_events"]
        ), f"Column '{col}' missing from alert_events. Got: {sorted(tables['alert_events'])}"


class TestArticleVersionsTable:
    """article_versions must exist with change tracking columns."""

    EXPECTED_COLUMNS = {
        "id",
        "article_id",
        "version",
        "title",
        "body",
        "summary",
        "category",
        "score",
        "changed_fields",
        "created_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "article_versions"
        ), "article_versions table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "article_versions"), "article_versions table missing"
        assert col in tables["article_versions"], (
            f"Column '{col}' missing from article_versions. "
            f"Got: {sorted(tables['article_versions'])}"
        )


class TestAuditLogTable:
    """audit_log must exist with security monitoring columns.

    Note: The design doc specifies 'occurred_at' but the ORM model uses
    'created_at'.  The DuckDB schema should match the ORM model (created_at).
    """

    EXPECTED_COLUMNS = {
        "id",
        "key_id",
        "action",
        "target_type",
        "target_id",
        "detail",
        "client_ip",
        "user_agent",
        "created_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(
            tables, "audit_log"
        ), "audit_log table is missing from SCHEMA_QUERIES. " "Found tables: " + ", ".join(
            sorted(tables)
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "audit_log"), "audit_log table missing"
        assert (
            col in tables["audit_log"]
        ), f"Column '{col}' missing from audit_log. Got: {sorted(tables['audit_log'])}"


class TestLLMCompareHourlyTable:
    """llm_compare_hourly must exist matching the PostgreSQL model."""

    EXPECTED_COLUMNS = {
        "id",
        "time_bucket",
        "call_point",
        "primary_model",
        "candidate_model",
        "comparison_count",
        "primary_latency_sum",
        "candidate_latency_sum",
        "primary_success_count",
        "candidate_success_count",
        "created_at",
    }

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "llm_compare_hourly"), (
            "llm_compare_hourly table is missing from SCHEMA_QUERIES. "
            "Found tables: " + ", ".join(sorted(tables))
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "llm_compare_hourly"), "llm_compare_hourly table missing"
        assert col in tables["llm_compare_hourly"], (
            f"Column '{col}' missing from llm_compare_hourly. "
            f"Got: {sorted(tables['llm_compare_hourly'])}"
        )


class TestArticlesView:
    """The articles VIEW must be defined for backward compatibility after vertical split."""

    def test_view_queries_exported(self):
        """VIEW_QUERIES must be exported from duckdb_schema module."""
        import core.db.duckdb_schema as mod

        assert hasattr(mod, "VIEW_QUERIES"), (
            "VIEW_QUERIES is not exported from core.db.duckdb_schema. "
            "The articles VIEW definition is required for backward compatibility "
            "after the vertical split."
        )

    def test_articles_view_defined(self):
        """An articles VIEW must be defined joining articles_core + article_bodies + article_analysis."""
        views = parse_views_from_module()
        assert "articles" in views, (
            "articles VIEW is not defined in VIEW_QUERIES. Found views: " + ", ".join(sorted(views))
            if views
            else "No views found at all."
        )


# ── Task 1.2 — source_authorities field completeness ─────────


class TestSourceAuthoritiesCompleteness:
    """source_authorities must have manual_score, final_score, article_count, last_crawled_at."""

    REQUIRED_COLUMNS = {"manual_score", "final_score", "article_count", "last_crawled_at"}

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "source_authorities"), (
            "source_authorities table is missing from SCHEMA_QUERIES. "
            "Found tables: " + ", ".join(sorted(tables))
        )

    @pytest.mark.parametrize("col", sorted(REQUIRED_COLUMNS))
    def test_has_required_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "source_authorities"), "source_authorities table missing"
        assert col in tables["source_authorities"], (
            f"Column '{col}' missing from source_authorities. "
            f"Got: {sorted(tables['source_authorities'])}"
        )


# ── Task 1.3 — unknown_relation_types column name consistency ─


class TestUnknownRelationTypesColumnNames:
    """unknown_relation_types must use raw_type, hit_count, context — NOT name, occurrence_count."""

    EXPECTED_COLUMNS = {"raw_type", "hit_count", "context"}
    FORBIDDEN_COLUMNS = {"name", "occurrence_count"}

    def test_table_exists(self):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "unknown_relation_types"), (
            "unknown_relation_types table is missing from SCHEMA_QUERIES. "
            "Found tables: " + ", ".join(sorted(tables))
        )

    @pytest.mark.parametrize("col", sorted(EXPECTED_COLUMNS))
    def test_has_correct_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "unknown_relation_types"), "unknown_relation_types table missing"
        assert col in tables["unknown_relation_types"], (
            f"Column '{col}' missing from unknown_relation_types. "
            f"Got: {sorted(tables['unknown_relation_types'])}"
        )

    @pytest.mark.parametrize("col", sorted(FORBIDDEN_COLUMNS))
    def test_does_not_have_wrong_column(self, col):
        tables = parse_tables_from_schema()
        assert _has_table(tables, "unknown_relation_types"), "unknown_relation_types table missing"
        assert col not in tables["unknown_relation_types"], (
            f"Forbidden column '{col}' found in unknown_relation_types. "
            f"The correct column names are: raw_type, hit_count, context. "
            f"Got: {sorted(tables['unknown_relation_types'])}"
        )


# ── Sequence completeness ────────────────────────────────────


class TestSequenceCompleteness:
    """Verify SEQUENCE_QUERIES covers all BIGINT PK tables that need sequences."""

    # Tables that use BIGINT PK with nextval() in DuckDB
    SEQUENCE_TABLES = {
        "source_authorities",
        "pending_sync",
        "llm_failure_records",
        "llm_usage_hourly",
        "entity_vectors",
        "relation_types",
        "relation_type_aliases",
        "unknown_relation_types",
    }

    # New tables that also need sequences
    NEW_SEQUENCE_TABLES = {
        "community_vectors",
        "sentiment_shifts",
        "daily_briefings",
        "daily_briefing_items",
        "api_keys",
        "alert_rules",
        "alert_events",
        "article_versions",
        "audit_log",
        "llm_compare_hourly",
    }

    def _parse_sequence_names(self) -> set[str]:
        """Extract sequence names from SEQUENCE_QUERIES."""
        names: set[str] = set()
        for query in SEQUENCE_QUERIES:
            match = re.search(
                r"CREATE\s+SEQUENCE\s+IF\s+NOT\s+EXISTS\s+(\w+)", query, re.IGNORECASE
            )
            if match:
                names.add(match.group(1))
        return names

    @pytest.mark.parametrize("table", sorted(SEQUENCE_TABLES))
    def test_existing_table_has_sequence(self, table):
        seq_names = self._parse_sequence_names()
        expected_seq = f"{table}_seq"
        assert (
            expected_seq in seq_names
        ), f"Sequence '{expected_seq}' missing from SEQUENCE_QUERIES. Found: {sorted(seq_names)}"

    @pytest.mark.parametrize("table", sorted(NEW_SEQUENCE_TABLES))
    def test_new_table_has_sequence(self, table):
        seq_names = self._parse_sequence_names()
        expected_seq = f"{table}_seq"
        assert expected_seq in seq_names, (
            f"Sequence '{expected_seq}' missing from SEQUENCE_QUERIES for new table '{table}'. "
            f"Found: {sorted(seq_names)}"
        )


# ── DDL-level default and constraint tests ────────────────────


def _find_table_ddl(table_name: str) -> str | None:
    """Find the DDL string for a given table name in SCHEMA_QUERIES."""
    for query in SCHEMA_QUERIES:
        if f"CREATE TABLE IF NOT EXISTS {table_name}" in query:
            return query
    return None


class TestArticlesCoreDDL:
    """DDL-level assertions for articles_core defaults and constraints."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("articles_core")
        assert cls.ddl is not None, "articles_core table not found in SCHEMA_QUERIES"

    def test_document_type_default(self):
        assert "document_type VARCHAR DEFAULT 'news'" in self.ddl

    def test_doc_metadata_default(self):
        assert "doc_metadata JSON DEFAULT '{}'" in self.ddl

    def test_version_default(self):
        assert "version INTEGER DEFAULT 1" in self.ddl


class TestArticleAnalysisDDL:
    """DDL-level assertions for article_analysis defaults."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("article_analysis")
        assert cls.ddl is not None, "article_analysis table not found in SCHEMA_QUERIES"

    def test_data_conflicts_default(self):
        assert "data_conflicts JSON DEFAULT '[]'" in self.ddl


class TestArticleBodiesDDL:
    """DDL-level assertions for article_bodies constraints."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("article_bodies")
        assert cls.ddl is not None, "article_bodies table not found in SCHEMA_QUERIES"

    def test_article_id_primary_key(self):
        assert "article_id UUID PRIMARY KEY" in self.ddl


class TestArticlesViewDDL:
    """DDL-level assertions for articles VIEW join structure."""

    @classmethod
    def setup_class(cls):
        from core.db.duckdb_schema import VIEW_QUERIES

        cls.view_ddl = None
        for query in VIEW_QUERIES:
            if "CREATE VIEW IF NOT EXISTS articles" in query:
                cls.view_ddl = query
                break
        assert cls.view_ddl is not None, "articles VIEW not found in VIEW_QUERIES"

    def test_joins_three_tables(self):
        assert "articles_core" in self.view_ddl
        assert "article_bodies" in self.view_ddl
        assert "article_analysis" in self.view_ddl

    def test_uses_left_join(self):
        assert "LEFT JOIN" in self.view_ddl
