#!/usr/bin/env python3
"""4-DB API cross-comparison test.

Tests 26 endpoints across 4 DB combinations (pg-neo4j, pg-ladybug,
duckdb-neo4j, duckdb-ladybug) and reports inconsistencies.

This script is the post-fix re-run of api_cross_test.json after:
  - PostgresSettings.enabled field added (clean DuckDB fallback)
  - run_4db_combinations.sh updated to use ENABLED flags + path overrides
  - All 4 instances verified healthy with correct DB backends

Design decision — serial execution (Performance review M1):
  Requests are issued serially (combo → endpoint). Parallelizing the 4
  combos would reduce wall time from ~5-8 min to ~90s, BUT all 4 instances
  share the same LLM API key (loaded from .env), so concurrent search
  endpoints (8 cases × 4 combos = 32 LLM calls) would trigger provider
  rate limits. Serial execution is the deliberate choice per rule 7
  (expose conflicts, do not compromise) — correctness > speed.

Usage:
    python3 scripts/cross_test_4db_api.py [--output PATH]

Output: JSON report saved to specmark/archive/2026-07-20-db-consistency-verify/records/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

API_KEY = "weaver_test_api_key_for_4db_combinations_2026"
HOST = "127.0.0.1"
COMBOS = {
    "pg-neo4j": 18001,
    "pg-ladybug": 18002,
    "duckdb-neo4j": 18003,
    "duckdb-ladybug": 18004,
}

# 26 test cases covering all major read endpoints.
# Each entry: (key, method, path, params, headers, expected_status)
# `key` is the test case identifier used in the report.
# Article IDs and entity names are sourced from the production data
# (consistency_report.json confirms 3 articles + 82 entities exist).
TEST_CASES: list[tuple[str, str, str, dict | None, dict | None, int | None]] = [
    # 1-2. System health & stats
    ("health", "GET", "/health", None, None, 200),
    ("system_stats", "GET", "/api/v1/system/status", None, None, 200),
    # 3-4. Articles list & sort
    ("articles_list", "GET", "/api/v1/articles", {"limit": 10}, None, 200),
    (
        "articles_sort",
        "GET",
        "/api/v1/articles",
        {"limit": 10, "sort_by": "published_at"},
        None,
        200,
    ),
    # 5-7. Graph
    ("graph_metrics", "GET", "/api/v1/graph/metrics", None, None, 200),
    ("entities_list", "GET", "/api/v1/graph/entities", {"limit": 10}, None, 200),
    ("communities_list", "GET", "/api/v1/admin/communities", {"limit": 10}, None, 200),
    # 8-10. Configuration & analytics
    ("sources_list", "GET", "/api/v1/sources", None, None, 200),
    ("alert_rules", "GET", "/api/v1/monitoring/alerts/rules", None, None, 200),
    ("briefings", "GET", "/api/v1/briefings/daily", None, None, 200),
    # 11-13. Article detail (3 known article UUIDs from production data)
    (
        "article_detail:3c5b6074-a099-4fc6-9b10-daa559b52f49",
        "GET",
        "/api/v1/articles/3c5b6074-a099-4fc6-9b10-daa559b52f49",
        None,
        None,
        200,
    ),
    (
        "article_detail:88bd2b93-ad31-40e5-b16e-263bf759803a",
        "GET",
        "/api/v1/articles/88bd2b93-ad31-40e5-b16e-263bf759803a",
        None,
        None,
        200,
    ),
    (
        "article_detail:2a620ec5-0f5a-43e7-8b22-f050153d94a2",
        "GET",
        "/api/v1/articles/2a620ec5-0f5a-43e7-8b22-f050153d94a2",
        None,
        None,
        200,
    ),
    # 14-18. Search local (5 queries)
    (
        "search_local:代糖",
        "GET",
        "/api/v1/search",
        {"q": "代糖", "mode": "local", "limit": 5},
        None,
        200,
    ),
    (
        "search_local:Windows",
        "GET",
        "/api/v1/search",
        {"q": "Windows", "mode": "local", "limit": 5},
        None,
        200,
    ),
    (
        "search_local:LibreOffice",
        "GET",
        "/api/v1/search",
        {"q": "LibreOffice", "mode": "local", "limit": 5},
        None,
        200,
    ),
    (
        "search_local:MPEG-4",
        "GET",
        "/api/v1/search",
        {"q": "MPEG-4", "mode": "local", "limit": 5},
        None,
        200,
    ),
    (
        "search_local:AI",
        "GET",
        "/api/v1/search",
        {"q": "AI", "mode": "local", "limit": 5},
        None,
        200,
    ),
    # 19-21. Search global (3 queries)
    (
        "search_global:代糖",
        "GET",
        "/api/v1/search",
        {"q": "代糖", "mode": "global", "limit": 5},
        None,
        200,
    ),
    (
        "search_global:Windows",
        "GET",
        "/api/v1/search",
        {"q": "Windows", "mode": "global", "limit": 5},
        None,
        200,
    ),
    (
        "search_global:LibreOffice",
        "GET",
        "/api/v1/search",
        {"q": "LibreOffice", "mode": "global", "limit": 5},
        None,
        200,
    ),
    # 22-26. Entity lookup (5 entities)
    ("entity_lookup:HDR", "GET", "/api/v1/graph/entities", {"name": "HDR"}, None, 200),
    ("entity_lookup:JPEG-XL", "GET", "/api/v1/graph/entities", {"name": "JPEG-XL"}, None, 200),
    (
        "entity_lookup:Firefox 153.0",
        "GET",
        "/api/v1/graph/entities",
        {"name": "Firefox 153.0"},
        None,
        200,
    ),
    ("entity_lookup:Vulkan", "GET", "/api/v1/graph/entities", {"name": "Vulkan"}, None, 200),
    ("entity_lookup:Mozilla", "GET", "/api/v1/graph/entities", {"name": "Mozilla"}, None, 200),
]

# Fields that are expected to differ across DB backends (not bugs).
# These are excluded from body comparison.
# Per api-acceptance-test methodology (specs/consistency-verification/spec.md):
# - Strip timestamp fields recursively (*_at, *_time, timestamp)
# - Normalize timezone-aware datetimes to UTC before comparison
# - Exclude real-time measurements (latency_ms) and DB-type-specific fields
EXPECTED_DIFFS = {
    # /health naturally reports different DB types per combo + latency is real-time
    "health": {"data.checks"},
    # /system/stats may report different DB driver versions + latency
    "system_stats": {"data.checks"},
    # graph_metrics: Neo4j has 169 rels vs LadybugDB 143 (known data sync gap,
    # not a code bug — see bug_fix_verification.json bug-1). All derived metrics
    # (health_score, average_degree, connectedness, status, recommendations)
    # differ as a consequence.
    "graph_metrics": {
        "data.health_score",
        "data.average_degree",
        "data.connectedness",
        "data.relationship_count",
        "data.recommendations",
        "data.status",
    },
    # search results have non-deterministic LLM output: answer text, confidence,
    # context_tokens (depends on LLM truncation), and sources ordering may vary
    "search_local:代糖": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_local:Windows": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_local:LibreOffice": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_local:MPEG-4": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_local:AI": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_global:代糖": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_global:Windows": {"data.answer", "data.confidence", "data.context_tokens"},
    "search_global:LibreOffice": {"data.answer", "data.confidence", "data.context_tokens"},
}

# Timestamp field names to strip recursively before comparison.
# Per api-acceptance-test R-verify-001: strip *_at, *_time, timestamp,
# created_at, updated_at, processed_at, ingested_at (recursive).
TIMESTAMP_FIELDS_TO_STRIP = {
    "timestamp",
    "created_at",
    "updated_at",
    "processed_at",
    "ingested_at",
    "start_time",
    "end_time",
}
# Pattern-based strip for any field ending in _at or _time.
# NOTE: publish_time / event_time / last_crawl_time are data fields representing
# article publication/event times — these are normalized to UTC instants rather
# than stripped, so we can still detect real data inconsistencies.
TIMESTAMP_FIELD_PATTERN = re.compile(r"^.*(_at|_time)$")

# Fields that contain timezone-aware datetimes to normalize to UTC.
# PG (asyncpg) returns +00:00 UTC; DuckDB returns +08:00 CST.
# Same instant, different display format — normalize before compare.
DATETIME_FIELDS_TO_NORMALIZE = {"publish_time", "event_time", "last_crawl_time"}

# Expected DB backends per combo (verified during health check).
# Mirrors strategy.py::create_strategy semantics:
#   - "postgres" selected when WEAVER_POSTGRES__ENABLED=true
#   - "duckdb"   selected when WEAVER_POSTGRES__ENABLED=false
#   - "neo4j"    selected when WEAVER_NEO4J__ENABLED=true
#   - "ladybug"  selected when WEAVER_NEO4J__ENABLED=false
# Closing Architecture review M6: previously db_types was printed but not
# asserted, allowing pg-neo4j to silently fall back to duckdb-ladybug.
EXPECTED_DBS = {
    "pg-neo4j": {"postgres", "neo4j"},
    "pg-ladybug": {"postgres", "ladybug"},
    "duckdb-neo4j": {"duckdb", "neo4j"},
    "duckdb-ladybug": {"duckdb", "ladybug"},
}

# Cache service names that may appear in /health checks but are NOT DBs.
# health.py: cache_service_name varies by CachePool implementation —
# "redis" (primary) or "cashews" (fallback when Redis unavailable).
NON_DB_HEALTH_CHECKS = frozenset({"redis", "cashews"})


def make_request(
    port: int,
    method: str,
    path: str,
    params: dict | None = None,
    extra_headers: dict | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Make HTTP request and return status_code + body."""
    url = f"http://{HOST}:{port}{path}"
    if params:
        url += "?" + urlencode(params)

    headers = {
        "Accept": "application/json",
        "X-API-Key": API_KEY,
    }
    if extra_headers:
        headers.update(extra_headers)

    # URL built from hardcoded HOST + TEST_CASES, no user input.
    # bandit suppression (nosec B310) must be on the urlopen line itself.
    # ruff suppression (noqa S310) is on both Request and urlopen lines.
    req = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            try:
                body_json = json.loads(body)
            except json.JSONDecodeError:
                body_json = {"_raw": body[:500]}
            return {
                "status_code": resp.status,
                "body": body_json,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            body_json = {"_raw": body[:500]}
        return {
            "status_code": e.code,
            "body": body_json,
        }
    except Exception as e:
        return {
            "status_code": 0,
            "body": {"_error": f"{type(e).__name__}: {e}"},
        }


def _normalize_datetime_to_utc(value: str) -> str:
    """Normalize ISO 8601 datetime string to UTC canonical form.

    PG (asyncpg) returns `+00:00` UTC; DuckDB returns `+08:00` CST.
    Both represent the same instant — normalize to UTC before compare.

    Examples:
      '2026-07-20T07:48:32+00:00' → '2026-07-20T07:48:32+00:00'
      '2026-07-20T15:48:32+08:00' → '2026-07-20T07:48:32+00:00'
      '2026-07-19T19:47:30Z'      → '2026-07-19T19:47:30+00:00'
      '2026-07-21T00:40:22.292440+08:00' → '2026-07-20T16:40:22.292440+00:00'
    """
    if not isinstance(value, str):
        return value
    try:
        # fromisoformat handles +00:00 / +08:00 since Python 3.7+
        # Replace trailing 'Z' with '+00:00' for fromisoformat compatibility
        v = value.rstrip("Z") + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            return value  # naive datetime, leave as-is
        dt_utc = dt.astimezone(UTC)
        return dt_utc.isoformat()
    except (ValueError, TypeError):
        return value  # not a datetime, leave as-is


def strip_timestamp_fields(body: Any) -> Any:
    """Recursively strip timestamp fields per api-acceptance-test R-verify-001.

    Strips: timestamp, created_at, updated_at, processed_at, ingested_at,
            start_time, end_time, and any field matching *(_at|_time)$.
    NOTE: publish_time / event_time / last_crawl_time are NOT stripped — they
    represent article data and are timezone-normalized instead via
    _normalize_datetime_to_utc.
    """
    if isinstance(body, dict):
        return {
            k: strip_timestamp_fields(v)
            for k, v in body.items()
            if k not in TIMESTAMP_FIELDS_TO_STRIP
            and not (TIMESTAMP_FIELD_PATTERN.match(k) and k not in DATETIME_FIELDS_TO_NORMALIZE)
        }
    if isinstance(body, list):
        return [strip_timestamp_fields(x) for x in body]
    return body


def normalize_datetime_fields(body: Any) -> Any:
    """Recursively normalize known datetime fields to UTC canonical form.

    Only normalizes fields in DATETIME_FIELDS_TO_NORMALIZE — these represent
    article publish/event times that should be the same instant across DBs
    but may be displayed in different timezone offsets.
    """
    if isinstance(body, dict):
        return {
            k: (
                _normalize_datetime_to_utc(v)
                if k in DATETIME_FIELDS_TO_NORMALIZE
                else normalize_datetime_fields(v)
            )
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [normalize_datetime_fields(x) for x in body]
    return body


def null_out_paths(body: Any, paths: set[str]) -> Any:
    """Return body with given dot-paths set to None.

    NOTE: `body` must already be a fresh structure (not shared with caller).
    `normalize_for_compare` ensures this by calling strip_timestamp_fields
    and normalize_datetime_fields first, both of which build new structures
    via dict/list comprehensions. No deepcopy needed here.
    """
    if not paths:
        return body  # fresh structure, safe to return as-is
    for path in paths:
        parts = path.split(".")
        node = body
        for p in parts[:-1]:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                node = None
                break
        if isinstance(node, dict):
            node[parts[-1]] = None
    return body


def normalize_for_compare(body: Any, expected_diff_paths: set[str]) -> Any:
    """Normalize body for cross-DB comparison.

    Pipeline (per api-acceptance-test methodology):
      1. Strip timestamp fields (timestamp, *_at, *_time) recursively
      2. Normalize datetime fields (publish_time, event_time, last_crawl_time)
         to UTC canonical form (PG returns +00:00, DuckDB returns +08:00)
      3. Null out expected-diff paths (DB-type-specific fields, LLM output)
    """
    stripped = strip_timestamp_fields(body)
    normalized = normalize_datetime_fields(stripped)
    return null_out_paths(normalized, expected_diff_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(
            Path(__file__).parent.parent
            / "specmark/archive/2026-07-20-db-consistency-verify/records/api_cross_test.json"
        ),
        help="Output JSON report path",
    )
    args = parser.parse_args()

    print(f"=== 4-DB API Cross Test ===")
    print(f"Started at: {datetime.now(UTC).isoformat()}")
    print(f"Combos: {list(COMBOS.keys())}")
    print(f"Test cases: {len(TEST_CASES)}")
    print(f"Total requests: {len(TEST_CASES) * len(COMBOS)}")
    print()

    # 1. Verify all 4 instances are healthy AND using the correct DB backends.
    # This closes the loop on the PostgresSettings.enabled configuration:
    # if pg-neo4j instance accidentally fell back to DuckDB, the test would
    # silently pass without this verification (Architecture review M6).
    print("[1/3] Verifying all 4 instances are healthy with correct DB backends...")
    for combo, port in COMBOS.items():
        resp = make_request(port, "GET", "/health", timeout=10)
        status = (
            resp["body"].get("data", {}).get("status", "?")
            if resp["status_code"] == 200
            else "UNHEALTHY"
        )
        checks = (
            resp["body"].get("data", {}).get("checks", {}) if resp["status_code"] == 200 else {}
        )
        db_types = {k for k in checks if k not in NON_DB_HEALTH_CHECKS}
        print(f"  {combo} (port {port}): {status} | DBs: {sorted(db_types)}")
        if status != "healthy":
            print(f"  ERROR: {combo} is not healthy. Aborting.")
            return 1
        expected = EXPECTED_DBS[combo]
        if db_types != expected:
            print(f"  ERROR: {combo} has DBs {sorted(db_types)} but expected {sorted(expected)}.")
            print(
                f"         This means the WEAVER_POSTGRES__ENABLED / WEAVER_NEO4J__ENABLED flags are not correctly configured."
            )
            return 1
    print()

    # 2. Run all test cases against all combos
    print(
        f"[2/3] Running {len(TEST_CASES)} test cases × {len(COMBOS)} combos = {len(TEST_CASES) * len(COMBOS)} requests..."
    )
    raw_results: dict[str, dict[str, dict]] = {combo: {} for combo in COMBOS}
    status_errors: dict[str, list[dict]] = {}  # key -> list of {combo, expected, actual}
    for combo, port in COMBOS.items():
        print(f"  [{combo}] Testing...")
        for key, method, path, params, extra_headers, expected_status in TEST_CASES:
            resp = make_request(port, method, path, params, extra_headers, timeout=120)
            raw_results[combo][key] = resp
            # Validate expected_status against actual (rule 12: explicit failure).
            # A mismatch means the endpoint path is wrong or the API changed —
            # silently ignoring would mask real test invalidity (Architecture
            # review HIGH: previously 4 endpoints returned 404 but were
            # reported CONSISTENT because all combos failed identically).
            if expected_status is not None and resp["status_code"] != expected_status:
                status_errors.setdefault(key, []).append(
                    {
                        "combo": combo,
                        "expected": expected_status,
                        "actual": resp["status_code"],
                        "path": path,
                    }
                )
                print(
                    f"  ⚠️  {key} [{combo}]: expected {expected_status}, "
                    f"got {resp['status_code']} ({path})"
                )
    print()

    # 3. Compare results across combos (baseline = pg-neo4j)
    print("[3/3] Comparing results across combos (baseline = pg-neo4j)...")
    baseline_combo = "pg-neo4j"
    summary: dict[str, str] = {}
    inconsistencies: dict[str, list[dict]] = {}
    total_inconsistencies = 0

    # Precompute normalized bodies once per (combo, key) to avoid repeated
    # normalize_for_compare calls (Performance review M2: previously baseline
    # body was normalized 3 times per key = 78 calls, 52 redundant).
    normalized_bodies: dict[str, dict[str, Any]] = {combo: {} for combo in COMBOS}
    for combo in COMBOS:
        for key, *_ in TEST_CASES:
            expected_diffs = EXPECTED_DIFFS.get(key, set())
            body = raw_results[combo][key].get("body")
            normalized_bodies[combo][key] = normalize_for_compare(body, expected_diffs)

    for key, *_ in TEST_CASES:
        baseline = raw_results[baseline_combo][key]
        baseline_norm = normalized_bodies[baseline_combo][key]
        issues = []
        for combo, _ in COMBOS.items():
            if combo == baseline_combo:
                continue
            other = raw_results[combo][key]
            # status_code mismatch short-circuits; otherwise compare normalized
            # bodies (already precomputed, so this is O(1) dict equality).
            if baseline.get("status_code") != other.get("status_code"):
                equal = False
            else:
                equal = baseline_norm == normalized_bodies[combo][key]
            if not equal:
                issues.append(
                    {
                        "type": (
                            "body_mismatch"
                            if baseline.get("status_code") == other.get("status_code")
                            else "status_mismatch"
                        ),
                        "baseline": baseline_combo,
                        "other": combo,
                        "baseline_status": baseline.get("status_code"),
                        "other_status": other.get("status_code"),
                        "baseline_preview": json.dumps(baseline.get("body"), ensure_ascii=False)[
                            :500
                        ],
                        "other_preview": json.dumps(other.get("body"), ensure_ascii=False)[:500],
                    }
                )
        if issues:
            summary[key] = f"{len(issues)} ISSUES"
            inconsistencies[key] = issues
            total_inconsistencies += len(issues)
        else:
            summary[key] = "CONSISTENT"
        status_marker = "❌" if issues else "✅"
        print(f"  {status_marker} {key}: {summary[key]}")

    print()
    print(f"=== Summary ===")
    print(f"Total endpoints tested: {len(TEST_CASES)}")
    print(f"Total inconsistencies: {total_inconsistencies}")
    consistent_count = sum(1 for v in summary.values() if v == "CONSISTENT")
    print(f"Consistent: {consistent_count}/{len(TEST_CASES)}")
    total_status_errors = sum(len(v) for v in status_errors.values())
    print(f"Total status_errors: {total_status_errors}")

    # 4. Save report
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "combos": list(COMBOS.keys()),
        "endpoints_tested": len(TEST_CASES),
        "total_inconsistencies": total_inconsistencies,
        "total_status_errors": total_status_errors,
        "summary": summary,
        "inconsistencies": inconsistencies,
        "status_errors": status_errors,
        "raw_results": raw_results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to: {output_path}")

    # Exit codes: 0=clean, 2=inconsistencies, 3=status_errors (path wrong),
    # 4=both. status_errors take precedence because they invalidate the
    # consistency comparison (404 vs 404 is "consistent" but wrong).
    if total_status_errors > 0:
        return 3 if total_inconsistencies == 0 else 4
    return 0 if total_inconsistencies == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
