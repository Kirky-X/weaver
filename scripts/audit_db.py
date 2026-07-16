# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

"""Comprehensive DuckDB data quality audit script.

Checks:
- Phase 1a: NOT NULL field null violations
- Phase 1b: Business-critical nullable field null rates
- Phase 1c: Cross-table foreign key integrity
- Phase 1d: Enum value validity & business rules
- Phase 1e: 50% random sampling detailed check

Output: structured JSON report at temp/audit/duckdb_audit_report.json
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

# ── Configuration ────────────────────────────────────────────────────

DB_PATH = "data/weaver.duckdb"
OUTPUT_DIR = Path("temp/audit")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = OUTPUT_DIR / "duckdb_audit_report.json"

# Tables and their NOT NULL fields (per SQLAlchemy models)
NOT_NULL_FIELDS: dict[str, list[str]] = {
    "articles_core": [
        "id",
        "source_url",
        "title",
        "persist_status",
        "is_merged",
        "version",
        "document_type",
        "doc_metadata",
    ],
    "article_bodies": ["article_id", "body"],
    "article_analysis": [
        "article_id",
        "is_news",
        "verified_by_sources",
        "data_conflicts",
        "image_forensics",
    ],
    "article_processing": ["article_id", "retry_count"],
    "article_vectors": ["id", "article_id", "vector_type", "embedding", "model_id"],
    "article_versions": ["article_id", "version", "title", "body"],
    "entity_vectors": ["id", "neo4j_id", "embedding", "model_id"],
    "source_configs": [
        "id",
        "name",
        "url",
        "source_type",
        "enabled",
        "interval_minutes",
        "per_host_concurrency",
    ],
    "source_authorities": ["host"],
    "llm_usage_raw": [
        "id",
        "label",
        "call_point",
        "llm_type",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "cost_usd",
        "latency_ms",
        "success",
    ],
    "llm_usage_hourly": [
        "id",
        "time_bucket",
        "label",
        "call_point",
        "llm_type",
        "provider",
        "model",
        "call_count",
        "input_tokens_sum",
        "output_tokens_sum",
        "total_tokens_sum",
        "cached_tokens_sum",
        "reasoning_tokens_sum",
        "cost_usd_sum",
        "latency_avg_ms",
        "latency_min_ms",
        "latency_max_ms",
        "success_count",
        "failure_count",
    ],
    "llm_failure_records": ["id", "call_point", "provider", "error_type"],
    "llm_compare_hourly": [
        "id",
        "time_bucket",
        "call_point",
        "primary_model",
        "candidate_model",
        "comparison_count",
    ],
    "alert_rules": ["id", "entity_name", "metric", "operator", "threshold"],
    "alert_events": [
        "id",
        "rule_id",
        "entity_name",
        "metric_value",
        "triggered_at",
    ],
    "pending_sync": ["id", "article_id", "sync_type", "payload"],
    "saga_logs": [
        "id",
        "saga_id",
        "article_id",
        "step_name",
        "step_status",
        "started_at",
    ],
    "relation_types": ["id", "name", "name_en", "category"],
    "relation_type_aliases": ["id", "alias", "relation_type_id"],
    "unknown_relation_types": ["id", "raw_type"],
    "sentiment_shifts": [
        "id",
        "community_id",
        "shift_type",
        "direction",
        "magnitude",
        "confidence",
        "detected_at",
        "window_start",
        "window_end",
    ],
    "daily_briefings": ["id", "briefing_date"],
    "daily_briefing_items": ["id", "briefing_id", "article_id", "rank", "score"],
    "audit_log": ["id", "key_id", "action", "created_at"],
    "community_vectors": ["id", "community_id", "embedding"],
    "api_keys": ["id", "key_id", "key_hash", "expires_at"],
    "prompt_templates": ["id", "name", "template"],
}

# Business-critical nullable fields (should mostly have values for completed articles)
BUSINESS_FIELDS: dict[str, list[str]] = {
    "articles_core": [
        "source_host",
        "source_id",
        "category",
        "language",
        "region",
        "score",
        "sentiment_score",
        "credibility_score",
        "publish_time",
        "content_hash",
        "created_at",
        "updated_at",
    ],
    "article_bodies": ["summary"],
    "article_analysis": [
        "subjects",
        "key_data",
        "impact",
        "has_data",
        "quality_score",
        "sentiment",
        "primary_emotion",
        "source_credibility",
        "cross_verification",
        "content_check_score",
        "event_time",
    ],
    "article_processing": ["task_id", "processing_stage", "created_at", "updated_at"],
    "source_configs": ["credibility", "tier", "last_crawl_time", "created_at", "updated_at"],
    "source_authorities": ["authority", "tier", "final_score", "article_count"],
    "llm_usage_raw": ["article_id", "task_id", "created_at", "error_type"],
    "entity_vectors": ["updated_at"],
}

# Foreign key relationships to verify
FOREIGN_KEYS: list[tuple[str, str, str, str]] = [
    # (child_table, child_col, parent_table, parent_col)
    ("article_bodies", "article_id", "articles_core", "id"),
    ("article_analysis", "article_id", "articles_core", "id"),
    ("article_processing", "article_id", "articles_core", "id"),
    ("article_vectors", "article_id", "articles_core", "id"),
    ("article_versions", "article_id", "articles_core", "id"),
    ("articles_core", "merged_into", "articles_core", "id"),
    ("alert_events", "rule_id", "alert_rules", "id"),
    ("pending_sync", "article_id", "articles_core", "id"),
    ("daily_briefing_items", "briefing_id", "daily_briefings", "id"),
    ("daily_briefing_items", "article_id", "articles_core", "id"),
    ("relation_type_aliases", "relation_type_id", "relation_types", "id"),
    ("llm_failure_records", "article_id", "articles_core", "id"),
]

# Enum value sets for validation
ENUM_VALUES: dict[str, tuple[str, str, set[str]]] = {
    # (table, column, allowed_values)
    "persist_status": (
        "articles_core",
        "persist_status",
        {
            "pending",
            "processing",
            "pg_done",
            "neo4j_done",
            "ladybug_done",
            "neo4j_failed",
            "failed",
            "saga_started",
            "saga_pg_done",
            "saga_graph_done",
            "saga_indexed",
            "saga_completed",
            "saga_failed",
        },
    ),
    "category": (
        "articles_core",
        "category",
        {
            "政治",
            "军事",
            "经济",
            "科技",
            "社会",
            "文化",
            "体育",
            "国际",
        },
    ),
    "document_type": (
        "articles_core",
        "document_type",
        {
            "news",
            "blog",
            "report",
            "press_release",
            "social_media",
            "academic",
            "official",
            "other",
        },
    ),
    "vector_type": ("article_vectors", "vector_type", {"title", "content"}),
}


def safe_execute(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    """Execute SQL, return empty list on error."""
    try:
        return con.execute(sql).fetchall()
    except Exception as e:
        return [("__ERROR__", f"{type(e).__name__}: {e}")]


def phase_1a_not_null_checks(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Check NOT NULL fields for null violations."""
    findings = []
    for table, fields in NOT_NULL_FIELDS.items():
        # Check table exists
        exists = safe_execute(
            con,
            f"""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema='main' AND table_name='{table}'
        """,
        )
        if not exists or exists[0][0] == 0:
            findings.append(
                {
                    "table": table,
                    "check": "table_exists",
                    "status": "MISSING",
                    "severity": "HIGH",
                    "detail": f"Table {table} does not exist",
                }
            )
            continue

        # Get total row count
        count_result = safe_execute(con, f"SELECT COUNT(*) FROM {table}")
        if not count_result or count_result[0][0] == "__ERROR__":
            findings.append(
                {
                    "table": table,
                    "check": "row_count",
                    "status": "ERROR",
                    "severity": "HIGH",
                    "detail": count_result[0][1] if count_result else "unknown",
                }
            )
            continue
        total_rows = count_result[0][0]

        # Check each NOT NULL field
        for field in fields:
            # Check column exists
            col_exists = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema='main' AND table_name='{table}' AND column_name='{field}'
            """,
            )
            if not col_exists or col_exists[0][0] == 0:
                findings.append(
                    {
                        "table": table,
                        "field": field,
                        "check": "column_exists",
                        "status": "MISSING",
                        "severity": "HIGH",
                        "detail": f"Column {table}.{field} does not exist",
                    }
                )
                continue

            null_count_result = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM {table} WHERE {field} IS NULL
            """,
            )
            if not null_count_result or null_count_result[0][0] == "__ERROR__":
                findings.append(
                    {
                        "table": table,
                        "field": field,
                        "check": "null_count",
                        "status": "ERROR",
                        "severity": "HIGH",
                        "detail": null_count_result[0][1] if null_count_result else "unknown",
                    }
                )
                continue
            null_count = null_count_result[0][0]

            if null_count > 0:
                findings.append(
                    {
                        "table": table,
                        "field": field,
                        "check": "not_null_violation",
                        "status": "FAIL",
                        "severity": "CRITICAL",
                        "null_count": null_count,
                        "total_rows": total_rows,
                        "null_rate": round(null_count / total_rows, 4) if total_rows > 0 else 1.0,
                    }
                )
    return findings


def phase_1b_business_field_checks(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Check business-critical nullable fields for null rates."""
    findings = []
    for table, fields in BUSINESS_FIELDS.items():
        count_result = safe_execute(con, f"SELECT COUNT(*) FROM {table}")
        if not count_result or count_result[0][0] == "__ERROR__":
            continue
        total_rows = count_result[0][0]
        if total_rows == 0:
            findings.append(
                {
                    "table": table,
                    "check": "empty_table",
                    "status": "WARN",
                    "severity": "MEDIUM",
                    "detail": f"Table {table} has 0 rows",
                }
            )
            continue

        for field in fields:
            col_exists = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema='main' AND table_name='{table}' AND column_name='{field}'
            """,
            )
            if not col_exists or col_exists[0][0] == 0:
                continue

            null_count = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM {table} WHERE {field} IS NULL
            """,
            )[0][0]

            null_rate = round(null_count / total_rows, 4) if total_rows > 0 else 0
            # For completed articles, business fields should be filled
            severity = "LOW"
            if null_rate > 0.5:
                severity = "HIGH"
            elif null_rate > 0.2:
                severity = "MEDIUM"

            if null_count > 0:
                findings.append(
                    {
                        "table": table,
                        "field": field,
                        "check": "business_null",
                        "status": "WARN",
                        "severity": severity,
                        "null_count": null_count,
                        "total_rows": total_rows,
                        "null_rate": null_rate,
                    }
                )
    return findings


def phase_1c_foreign_key_checks(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Check foreign key integrity (orphaned records)."""
    findings = []
    for child_table, child_col, parent_table, parent_col in FOREIGN_KEYS:
        # Check both tables exist
        for t in (child_table, parent_table):
            exists = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='main' AND table_name='{t}'
            """,
            )[0][0]
            if exists == 0:
                findings.append(
                    {
                        "check": "fk_table_exists",
                        "table": t,
                        "status": "MISSING",
                        "severity": "HIGH",
                        "detail": f"Table {t} does not exist",
                    }
                )
                break
        else:
            # Check orphaned records
            orphans = safe_execute(
                con,
                f"""
                SELECT COUNT(*) FROM {child_table} c
                WHERE c.{child_col} IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM {parent_table} p WHERE p.{parent_col} = c.{child_col}
                )
            """,
            )[0][0]

            if orphans > 0:
                findings.append(
                    {
                        "check": "fk_integrity",
                        "status": "FAIL",
                        "severity": "HIGH",
                        "child_table": child_table,
                        "child_col": child_col,
                        "parent_table": parent_table,
                        "parent_col": parent_col,
                        "orphan_count": orphans,
                    }
                )
    return findings


def phase_1d_enum_and_rule_checks(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Check enum value validity and business rules."""
    findings = []

    # Enum value checks
    for _enum_name, (table, column, allowed) in ENUM_VALUES.items():
        exists = safe_execute(
            con,
            f"""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema='main' AND table_name='{table}' AND column_name='{column}'
        """,
        )[0][0]
        if exists == 0:
            continue

        # Find invalid enum values
        values_in = ",".join(f"'{v}'" for v in allowed)
        invalid = safe_execute(
            con,
            f"""
            SELECT {column}, COUNT(*) as cnt
            FROM {table}
            WHERE {column} IS NOT NULL AND {column} NOT IN ({values_in})
            GROUP BY {column}
            ORDER BY cnt DESC
        """,
        )
        if invalid:
            for val, cnt in invalid:
                findings.append(
                    {
                        "check": "enum_value",
                        "status": "FAIL",
                        "severity": "MEDIUM",
                        "table": table,
                        "column": column,
                        "invalid_value": val,
                        "count": cnt,
                        "allowed": sorted(allowed),
                    }
                )

    # Business rule: score range 0-1
    for table, col in [
        ("articles_core", "score"),
        ("articles_core", "sentiment_score"),
        ("articles_core", "credibility_score"),
        ("article_analysis", "quality_score"),
        ("article_analysis", "source_credibility"),
        ("article_analysis", "cross_verification"),
        ("article_analysis", "content_check_score"),
        ("source_configs", "credibility"),
        ("source_authorities", "authority"),
    ]:
        out_of_range = safe_execute(
            con,
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE {col} IS NOT NULL AND ({col} < 0 OR {col} > 1)
        """,
        )[0][0]
        if out_of_range > 0:
            findings.append(
                {
                    "check": "range_violation",
                    "status": "FAIL",
                    "severity": "MEDIUM",
                    "table": table,
                    "column": col,
                    "rule": "0 <= value <= 1",
                    "violation_count": out_of_range,
                }
            )

    # Business rule: merged_into ≠ id
    self_merge = safe_execute(
        con,
        """
        SELECT COUNT(*) FROM articles_core
        WHERE merged_into IS NOT NULL AND merged_into = id
    """,
    )[0][0]
    if self_merge > 0:
        findings.append(
            {
                "check": "self_merge",
                "status": "FAIL",
                "severity": "HIGH",
                "table": "articles_core",
                "violation_count": self_merge,
                "rule": "merged_into != id",
            }
        )

    # Business rule: interval_minutes range 5-1440
    bad_interval = safe_execute(
        con,
        """
        SELECT COUNT(*) FROM source_configs
        WHERE interval_minutes < 5 OR interval_minutes > 1440
    """,
    )[0][0]
    if bad_interval > 0:
        findings.append(
            {
                "check": "interval_range",
                "status": "FAIL",
                "severity": "MEDIUM",
                "table": "source_configs",
                "violation_count": bad_interval,
            }
        )

    # Business rule: source_configs.tier range 1-3
    bad_tier = safe_execute(
        con,
        """
        SELECT COUNT(*) FROM source_configs
        WHERE tier IS NOT NULL AND (tier < 1 OR tier > 3)
    """,
    )[0][0]
    if bad_tier > 0:
        findings.append(
            {
                "check": "tier_range",
                "status": "FAIL",
                "severity": "MEDIUM",
                "table": "source_configs",
                "violation_count": bad_tier,
            }
        )

    return findings


def phase_1e_sampling_check(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """50% random sampling detailed check on articles_core."""
    findings = []
    total = safe_execute(con, "SELECT COUNT(*) FROM articles_core")[0][0]
    if total == 0:
        return [{"check": "empty_articles", "status": "FAIL", "severity": "CRITICAL"}]

    sample_size = max(1, total // 2)
    # Use reservoir sampling via ORDER BY random()
    samples = safe_execute(
        con,
        f"""
        SELECT id, source_url, source_id, title, category, language, region,
               score, persist_status, publish_time, content_hash,
               created_at, updated_at
        FROM articles_core
        WHERE merged_into IS NULL
        ORDER BY random()
        LIMIT {sample_size}
    """,
    )

    # Aggregate field null rates in sample
    fields = [
        "source_url",
        "source_id",
        "title",
        "category",
        "language",
        "region",
        "score",
        "persist_status",
        "publish_time",
        "content_hash",
        "created_at",
        "updated_at",
    ]
    null_counts = dict.fromkeys(fields, 0)
    for row in samples:
        for i, f in enumerate(fields, start=1):
            if row[i] is None:
                null_counts[f] += 1

    for f in fields:
        if null_counts[f] > 0:
            rate = round(null_counts[f] / sample_size, 4)
            severity = "HIGH" if rate > 0.5 else ("MEDIUM" if rate > 0.2 else "LOW")
            findings.append(
                {
                    "check": "sample_null",
                    "status": "WARN",
                    "severity": severity,
                    "field": f,
                    "sample_size": sample_size,
                    "null_in_sample": null_counts[f],
                    "null_rate": rate,
                }
            )

    # Check completed articles have all key fields
    completed_nulls = safe_execute(
        con,
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN category IS NULL THEN 1 ELSE 0 END) as null_category,
            SUM(CASE WHEN language IS NULL THEN 1 ELSE 0 END) as null_language,
            SUM(CASE WHEN region IS NULL THEN 1 ELSE 0 END) as null_region,
            SUM(CASE WHEN score IS NULL THEN 1 ELSE 0 END) as null_score,
            SUM(CASE WHEN credibility_score IS NULL THEN 1 ELSE 0 END) as null_cred
        FROM articles_core
        WHERE persist_status = 'ladybug_done' AND merged_into IS NULL
    """,
    )
    if completed_nulls:
        row = completed_nulls[0]
        total_completed = row[0]
        if total_completed > 0:
            for label, cnt in [
                ("category", row[1]),
                ("language", row[2]),
                ("region", row[3]),
                ("score", row[4]),
                ("credibility_score", row[5]),
            ]:
                if cnt > 0:
                    findings.append(
                        {
                            "check": "completed_article_null",
                            "status": "FAIL",
                            "severity": "HIGH",
                            "field": label,
                            "completed_count": total_completed,
                            "null_count": cnt,
                            "null_rate": round(cnt / total_completed, 4),
                        }
                    )

    return findings


def main() -> int:
    print(f"[{datetime.now(UTC).isoformat()}] Starting DuckDB audit...")
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
    except Exception as e:
        print(f"FATAL: Cannot connect to DuckDB: {e}")
        return 1

    report = {
        "audit_time": datetime.now(UTC).isoformat(),
        "database": "DuckDB",
        "db_path": DB_PATH,
        "phases": {},
    }

    # Table overview
    tables = safe_execute(
        con,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='main' AND table_type='BASE TABLE'
        ORDER BY table_name
    """,
    )
    report["table_overview"] = {}
    for (tname,) in tables:
        cnt = safe_execute(con, f'SELECT COUNT(*) FROM "{tname}"')[0][0]
        report["table_overview"][tname] = cnt

    print(f"\n=== Phase 1a: NOT NULL field checks ===")
    report["phases"]["1a_not_null"] = phase_1a_not_null_checks(con)
    fail_count = sum(1 for f in report["phases"]["1a_not_null"] if f.get("status") == "FAIL")
    print(f"  Findings: {len(report['phases']['1a_not_null'])}, FAIL: {fail_count}")

    print(f"\n=== Phase 1b: Business field null checks ===")
    report["phases"]["1b_business_null"] = phase_1b_business_field_checks(con)
    print(f"  Findings: {len(report['phases']['1b_business_null'])}")

    print(f"\n=== Phase 1c: Foreign key integrity ===")
    report["phases"]["1c_foreign_keys"] = phase_1c_foreign_key_checks(con)
    fail_count = sum(1 for f in report["phases"]["1c_foreign_keys"] if f.get("status") == "FAIL")
    print(f"  Findings: {len(report['phases']['1c_foreign_keys'])}, FAIL: {fail_count}")

    print(f"\n=== Phase 1d: Enum & business rule checks ===")
    report["phases"]["1d_enum_rules"] = phase_1d_enum_and_rule_checks(con)
    fail_count = sum(1 for f in report["phases"]["1d_enum_rules"] if f.get("status") == "FAIL")
    print(f"  Findings: {len(report['phases']['1d_enum_rules'])}, FAIL: {fail_count}")

    print(f"\n=== Phase 1e: 50% random sampling ===")
    report["phases"]["1e_sampling"] = phase_1e_sampling_check(con)
    print(f"  Findings: {len(report['phases']['1e_sampling'])}")

    # Summary
    all_findings = []
    for phase_findings in report["phases"].values():
        all_findings.extend(phase_findings)
    report["summary"] = {
        "total_findings": len(all_findings),
        "critical": sum(1 for f in all_findings if f.get("severity") == "CRITICAL"),
        "high": sum(1 for f in all_findings if f.get("severity") == "HIGH"),
        "medium": sum(1 for f in all_findings if f.get("severity") == "MEDIUM"),
        "low": sum(1 for f in all_findings if f.get("severity") == "LOW"),
    }
    print(f"\n=== Summary ===")
    print(f"  Total findings: {report['summary']['total_findings']}")
    print(f"  CRITICAL: {report['summary']['critical']}")
    print(f"  HIGH: {report['summary']['high']}")
    print(f"  MEDIUM: {report['summary']['medium']}")
    print(f"  LOW: {report['summary']['low']}")

    con.close()

    # Write report
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\nReport saved to: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
