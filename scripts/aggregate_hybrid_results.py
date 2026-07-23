#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Aggregate hybrid DB test results across all 4 phases and compare consistency.

Phases:
  - Phase 1: PG + Neo4j + Redis (primary stack)
  - Phase 2: DuckDB + LadybugDB (full fallback)
  - Phase 3: PG + LadybugDB (hybrid: relational primary, graph fallback)
  - Phase 4: DuckDB + Neo4j (hybrid: graph primary, relational fallback)

Reads each phase's summary.json (produced by aggregate_results.py --phase
{1,2} for Phase 1/2 and by pytest --json-report for Phase 3/4), then compares:
  1. Per-phase totals (total/pass/fail/skip)
  2. Core endpoint response consistency across phases
  3. Slim-down contract verification (Phase 3/4 specific)

Output: specmark/changes/web-search-and-db-optimization/records/hybrid_comparison.json

Usage:
    uv run scripts/aggregate_hybrid_results.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# Phase 1/2 records live under the api-acceptance-test change (prior sprint).
PHASE1_DIR = Path("specmark/changes/api-acceptance-test/records/phase1")
PHASE2_DIR = Path("specmark/changes/api-acceptance-test/records/phase2")
# Phase 3/4 records live under the current change (web-search-and-db-optimization).
PHASE3_DIR = Path("specmark/changes/web-search-and-db-optimization/records/phase3")
PHASE4_DIR = Path("specmark/changes/web-search-and-db-optimization/records/phase4")
OUTPUT_FILE = Path("specmark/changes/web-search-and-db-optimization/records/hybrid_comparison.json")

# Core endpoints that must behave consistently across all 4 DB combinations.
# Each endpoint maps to:
#   - router: phase1/2 routers[] name (for routers[].fail extraction)
#   - phase3_test / phase4_test: phase3/4 tests[] nodeid keyword
#     (None = endpoint not exercised in that phase)
ENDPOINT_PHASE_MAP: dict[str, dict[str, str | None]] = {
    "GET /api/v1/health": {
        "router": "health",
        "phase3_test": "test_health_dependencies_returns_pg_ladybug",
        "phase4_test": "test_health_dependencies_returns_duckdb_neo4j",
    },
    "GET /api/v1/health/dependencies": {
        "router": "health",
        "phase3_test": "test_health_dependencies_returns_pg_ladybug",
        "phase4_test": "test_health_dependencies_returns_duckdb_neo4j",
    },
    "GET /api/v1/search": {
        "router": "search",
        "phase3_test": "test_search_returns_results_with_pg_title_enrichment",
        "phase4_test": "test_search_returns_results_with_duckdb_title_enrichment",
    },
    "GET /api/v1/articles/{id}": {
        "router": "articles",
        "phase3_test": "test_article_graph_node_only_stores_pg_id",
        "phase4_test": "test_article_graph_node_only_stores_pg_id",
    },
    "POST /api/v1/pipeline/trigger": {
        "router": "pipeline",
        "phase3_test": None,
        "phase4_test": None,
    },
}

# Test keywords that validate the Article slim-down contract (design.md §D2).
SLIM_DOWN_TEST_KEYWORDS = (
    "test_article_graph_node_only_stores_pg_id",
    "test_graph_repo_get_article_enriches_title_from_pg",
    "test_graph_repo_get_article_enriches_title_from_duckdb",
)


def _load_phase_summary(phase_dir: Path, phase_name: str) -> dict | None:
    """Load a phase's summary.json, returning None if missing or invalid."""
    summary_file = phase_dir / "summary.json"
    if not summary_file.exists():
        print(f"  [WARN] {phase_name}: {summary_file} not found — skipping")
        return None
    try:
        return json.loads(summary_file.read_text())
    except json.JSONDecodeError as exc:
        print(f"  [ERROR] {phase_name}: failed to parse {summary_file}: {exc}")
        return None


def _extract_totals(summary: dict | None) -> dict:
    """Extract total/pass/fail/skip from a phase summary.

    Handles two structures:
    - Phase 1/2: ``{totals: {total, pass, fail, skip, pass_rate_percent}}``
    - Phase 3/4 (pytest --json-report): ``{summary: {total, passed, failed, skipped}}``
    """
    if summary is None:
        return {"available": False, "total": 0, "pass": 0, "fail": 0, "skip": 0}
    totals = summary.get("totals")
    if not isinstance(totals, dict):
        # pytest --json-report fallback: summary.{total,passed,failed,skipped}
        report_summary = summary.get("summary")
        if isinstance(report_summary, dict):
            totals = {
                "total": report_summary.get("total", 0),
                "pass": report_summary.get("passed", 0),
                "fail": report_summary.get("failed", 0),
                "skip": report_summary.get("skipped", 0),
                "pass_rate_percent": round(
                    report_summary.get("passed", 0) / max(report_summary.get("total", 1), 1) * 100,
                    2,
                ),
            }
        else:
            totals = {}
    return {
        "available": True,
        "total": totals.get("total", 0),
        "pass": totals.get("pass", 0),
        "fail": totals.get("fail", 0),
        "skip": totals.get("skip", 0),
        "pass_rate_percent": totals.get("pass_rate_percent", 0.0),
    }


def _extract_endpoint_status_phase12(summary: dict | None, router_name: str) -> str:
    """Extract endpoint status from a Phase 1/2 summary.

    Reads ``summary.routers[]`` and returns:
    - ``"pass"`` if the matching router has 0 failures
    - ``"fail"`` if the matching router has ≥1 failure
    - ``"not_tested"`` if the router is absent
    - ``"unavailable"`` if summary is None
    """
    if summary is None:
        return "unavailable"
    routers = summary.get("routers", [])
    if not isinstance(routers, list):
        return "not_tested"
    for router in routers:
        if not isinstance(router, dict):
            continue
        if router.get("router") == router_name:
            return "fail" if router.get("fail", 0) > 0 else "pass"
    return "not_tested"


def _extract_endpoint_status_phase34(summary: dict | None, test_keyword: str | None) -> str:
    """Extract endpoint status from a Phase 3/4 pytest --json-report summary.

    Matches ``tests[].nodeid`` by ``test_keyword`` and aggregates outcomes:
    - ``"pass"`` if all matched tests have outcome=passed
    - ``"fail"`` if any matched test has outcome=failed
    - ``"skipped"`` if all matched tests have outcome=skipped
    - ``"mixed"`` if outcomes disagree (excluding failed)
    - ``"not_tested"`` if no match or test_keyword is None
    - ``"unavailable"`` if summary is None
    """
    if summary is None:
        return "unavailable"
    if test_keyword is None:
        return "not_tested"
    tests = summary.get("tests", [])
    if not isinstance(tests, list):
        return "not_tested"
    matched = [t for t in tests if isinstance(t, dict) and test_keyword in str(t.get("nodeid", ""))]
    if not matched:
        return "not_tested"
    outcomes = {str(t.get("outcome", "")).lower() for t in matched}
    if "failed" in outcomes:
        return "fail"
    if outcomes == {"passed"}:
        return "pass"
    if outcomes == {"skipped"}:
        return "skipped"
    return "mixed"


def _compare_endpoint_consistency(
    phases: dict[str, dict | None],
) -> list[dict]:
    """Compare core endpoint response status across all 4 phases.

    For each core endpoint in ``ENDPOINT_PHASE_MAP``, extract its status
    from each phase using phase-specific extraction logic:
    - Phase 1/2: from ``summary.routers[].fail`` count
    - Phase 3/4: from ``summary.tests[].outcome`` by nodeid keyword

    Returns the list of inconsistencies — endpoints where two or more
    phases ran the endpoint (``pass``/``fail``/``skipped``) but disagreed.
    Phases marked ``"not_tested"`` or ``"unavailable"`` do not count
    toward the consistency check, but are still reported in statuses.
    """
    inconsistencies: list[dict] = []

    for endpoint, mapping in ENDPOINT_PHASE_MAP.items():
        router_name = str(mapping["router"])
        statuses = {
            "phase1": _extract_endpoint_status_phase12(phases.get("phase1"), router_name),
            "phase2": _extract_endpoint_status_phase12(phases.get("phase2"), router_name),
            "phase3": _extract_endpoint_status_phase34(
                phases.get("phase3"), mapping["phase3_test"]
            ),
            "phase4": _extract_endpoint_status_phase34(
                phases.get("phase4"), mapping["phase4_test"]
            ),
        }

        comparable = {
            phase: status
            for phase, status in statuses.items()
            if status in ("pass", "fail", "skipped")
        }
        unique_statuses = set(comparable.values())
        if len(unique_statuses) > 1:
            inconsistencies.append(
                {
                    "endpoint": endpoint,
                    "statuses": statuses,
                    "comparable_phases": list(comparable.keys()),
                    "consistent": False,
                }
            )

    return inconsistencies


def _check_slim_down_test_outcome(summary: dict | None) -> str:
    """Check slim-down test outcome from a Phase 3/4 pytest summary.

    Returns:
        ``"passed"`` if all slim-down tests passed.
        ``"failed"`` if any slim-down test failed.
        ``"skipped"`` if all slim-down tests were skipped.
        ``"mixed"`` if outcomes disagree.
        ``"missing"`` if no slim-down tests found in summary.
        ``"unavailable"`` if summary is None.
    """
    if summary is None:
        return "unavailable"
    tests = summary.get("tests", [])
    if not isinstance(tests, list):
        return "missing"

    matched: list[dict] = []
    for t in tests:
        if not isinstance(t, dict):
            continue
        nodeid = str(t.get("nodeid", ""))
        if any(kw in nodeid for kw in SLIM_DOWN_TEST_KEYWORDS):
            matched.append(t)

    if not matched:
        return "missing"

    outcomes = {str(t.get("outcome", "")).lower() for t in matched}
    if "failed" in outcomes:
        return "failed"
    if outcomes == {"passed"}:
        return "passed"
    if outcomes == {"skipped"}:
        return "skipped"
    return "mixed"


def _verify_slim_down_contract(phase3: dict | None, phase4: dict | None) -> dict:
    """Verify Article graph node slim-down contract (design.md §D2).

    Checks that Phase 3/4 tests confirm:
    - Graph Article node stores only {id, pg_id}
    - Title/category/score come from relational DB via fetch_titles_by_pg_ids

    Returns per-phase outcome (``passed``/``failed``/``skipped``/``mixed``/
    ``missing``/``unavailable``) instead of a mere presence flag, so that
    a failing contract test is surfaced rather than silently reported as
    "present".
    """
    return {
        "contract": "Article graph node slim-down (design.md §D2)",
        "phase3_status": _check_slim_down_test_outcome(phase3),
        "phase4_status": _check_slim_down_test_outcome(phase4),
        "test_keywords": list(SLIM_DOWN_TEST_KEYWORDS),
    }


def aggregate() -> None:
    """Aggregate hybrid DB test results across all 4 phases."""
    print("=" * 80)
    print("Hybrid DB Test Results Aggregator (Phase 1-4)")
    print("=" * 80)

    # Load all phase summaries
    print("\nLoading phase summaries:")
    phase1 = _load_phase_summary(PHASE1_DIR, "Phase 1 (PG+Neo4j+Redis)")
    phase2 = _load_phase_summary(PHASE2_DIR, "Phase 2 (DuckDB+LadybugDB)")
    phase3 = _load_phase_summary(PHASE3_DIR, "Phase 3 (PG+LadybugDB)")
    phase4 = _load_phase_summary(PHASE4_DIR, "Phase 4 (DuckDB+Neo4j)")

    phases = {
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
        "phase4": phase4,
    }

    # Extract totals
    totals = {
        "phase1": _extract_totals(phase1),
        "phase2": _extract_totals(phase2),
        "phase3": _extract_totals(phase3),
        "phase4": _extract_totals(phase4),
    }

    # Compare endpoint consistency
    inconsistencies = _compare_endpoint_consistency(phases)

    # Verify slim-down contract
    slim_down = _verify_slim_down_contract(phase3, phase4)

    # Build combined report
    report = {
        "report_type": "hybrid_db_comparison",
        "generated_at": datetime.now().isoformat(),
        "phases": {
            "phase1": {
                "name": "PG + Neo4j + Redis",
                "records_dir": str(PHASE1_DIR),
                **totals["phase1"],
            },
            "phase2": {
                "name": "DuckDB + LadybugDB",
                "records_dir": str(PHASE2_DIR),
                **totals["phase2"],
            },
            "phase3": {
                "name": "PG + LadybugDB",
                "records_dir": str(PHASE3_DIR),
                **totals["phase3"],
            },
            "phase4": {
                "name": "DuckDB + Neo4j",
                "records_dir": str(PHASE4_DIR),
                **totals["phase4"],
            },
        },
        "core_endpoints_checked": list(ENDPOINT_PHASE_MAP.keys()),
        "endpoint_consistency": {
            "inconsistencies": inconsistencies,
            "consistent": len(inconsistencies) == 0,
        },
        "slim_down_contract": slim_down,
        "summary": {
            "phases_available": sum(1 for t in totals.values() if t["available"]),
            "phases_missing": sum(1 for t in totals.values() if not t["available"]),
            "total_tests_across_phases": sum(t["total"] for t in totals.values()),
            "total_pass_across_phases": sum(t["pass"] for t in totals.values()),
            "total_fail_across_phases": sum(t["fail"] for t in totals.values()),
        },
    }

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # Print summary table
    print(f"\n{'Phase':<35} {'Available':>10} {'Total':>7} {'Pass':>7} {'Fail':>7} {'Skip':>7}")
    print("-" * 80)
    for phase_key, phase_data in report["phases"].items():
        avail = "Yes" if phase_data["available"] else "No"
        print(
            f"{phase_key} ({phase_data['name']:<24}) {avail:>10} "
            f"{phase_data['total']:>7} {phase_data['pass']:>7} "
            f"{phase_data['fail']:>7} {phase_data['skip']:>7}"
        )
    print("-" * 80)
    print(
        f"{'TOTAL':<35} {'':>10} {report['summary']['total_tests_across_phases']:>7} "
        f"{report['summary']['total_pass_across_phases']:>7} "
        f"{report['summary']['total_fail_across_phases']:>7}"
    )

    print(
        f"\nEndpoint consistency: {'PASS' if report['endpoint_consistency']['consistent'] else 'FAIL'}"
    )
    if inconsistencies:
        for inc in inconsistencies:
            print(f"  [INCONSISTENT] {inc['endpoint']}: {inc['statuses']}")

    print(f"\nSlim-down contract verification:")
    print(f"  Phase 3 (PG+LadybugDB): {slim_down['phase3_status']}")
    print(f"  Phase 4 (DuckDB+Neo4j): {slim_down['phase4_status']}")

    print(f"\nReport written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    aggregate()
