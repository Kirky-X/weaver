#!/usr/bin/env python
"""Cross-test API responses across 4 DB backend combinations.

For each combination (pg-neo4j=18001, pg-ladybug=18002, duckdb-neo4j=18003,
duckdb-ladybug=18004), hit the same set of read-only endpoints and compare
the responses pairwise to verify business-data parity across DB backends.

Comparison rules:
  - Strip volatile fields (*_at, *_time, timestamp, latency_ms, generated_at)
  - Sort lists by a stable key (id, name, title) before comparison
  - For floats, use math.isclose with rel_tol=1e-5, abs_tol=2e-6

Output: specmark/changes/db-consistency-verify/records/api_cross_test.json
Exit code: 0 = all consistent, 1 = inconsistencies found
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_KEY = "weaver_test_api_key_for_4db_combinations_2026"

COMBOS: dict[str, str] = {
    "pg-neo4j": "http://127.0.0.1:18001",
    "pg-ladybug": "http://127.0.0.1:18002",
    "duckdb-neo4j": "http://127.0.0.1:18003",
    "duckdb-ladybug": "http://127.0.0.1:18004",
}

# Volatile fields stripped before comparison.
VOLATILE_KEYS = {
    "created_at",
    "updated_at",
    "published_at",
    "timestamp",
    "generated_at",
    "processed_at",
    "indexed_at",
    "synced_at",
    "latency_ms",
    "latency",
    "queued_at",
    "started_at",
    "completed_at",
    "fetched_at",
    "analyzed_at",
    "ingested_at",
    "enriched_at",
}

# Real test data sampled from PG / Neo4j (see scripts/fetch_test_data.py).
REAL_ARTICLE_IDS = [
    "3c5b6074-a099-4fc6-9b10-daa559b52f49",
    "88bd2b93-ad31-40e5-b16e-263bf759803a",
    "2a620ec5-0f5a-43e7-8b22-f050153d94a2",
    "468baced-f015-48a4-8ae0-3120cf241b6a",
    "a001d463-2db6-4a6f-8df4-788387eda4d1",
]
REAL_SEARCH_QUERIES = ["代糖", "Windows", "LibreOffice", "MPEG-4", "AI"]
REAL_ENTITY_NAMES = ["HDR", "JPEG-XL", "Firefox 153.0", "Vulkan", "Mozilla"]


def _request(method: str, url: str, *, body: dict | None = None) -> tuple[int, Any]:
    """Send an HTTP request, returning (status_code, parsed_json_or_raw_text)."""
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        # url is built from hardcoded base_url + endpoint, no user input
        with urlopen(req, timeout=60) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            return exc.code, json.loads(raw) if raw else {"error": str(exc)}
        except json.JSONDecodeError:
            return exc.code, raw or {"error": str(exc)}
    except URLError as exc:
        return 0, {"error": f"connection: {exc}"}
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _strip_volatile(obj: Any) -> Any:
    """Recursively remove volatile fields and normalize for comparison."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v)
            for k, v in obj.items()
            if k not in VOLATILE_KEYS and not k.endswith(("_at", "_time"))
        }
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def _sort_lists(obj: Any, key_hint: str = "") -> Any:
    """Sort lists by a stable key when possible."""
    if isinstance(obj, dict):
        return {k: _sort_lists(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        items = [_sort_lists(x, key_hint) for x in obj]
        if not items:
            return items
        # Pick the first available stable key.
        for key in (
            "id",
            "article_id",
            "entity_id",
            "name",
            "canonical_name",
            "title",
            "host",
            "slug",
            "key",
        ):
            if isinstance(items[0], dict) and key in items[0]:
                try:
                    return sorted(items, key=lambda x: str(x.get(key, "")))
                except Exception:
                    return items
        # Fall back to sorting by JSON serialization for primitive lists.
        try:
            return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
        except Exception:
            return items
    return obj


def _normalize(obj: Any) -> Any:
    return _sort_lists(_strip_volatile(obj))


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-5, abs_tol=2e-6)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_values_equal(a[k], b[k]) for k in a)
    return a == b


def _wait_for_health(base: str, timeout: int = 300) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, body = _request("GET", f"{base}/health")
        if code == 200 and isinstance(body, dict):
            data = body.get("data", {})
            if data.get("status") == "healthy":
                return True
        time.sleep(5)
    return False


# ── Test endpoints ──────────────────────────────────────────────────────


def build_test_plan() -> list[tuple[str, str, str, dict | None]]:
    """Return list of (method, path, label, body) tuples."""
    plan: list[tuple[str, str, str, dict | None]] = [
        ("GET", "/health", "health", None),
        ("GET", "/api/v1/system/stats", "system_stats", None),
        ("GET", "/api/v1/articles?page=1&page_size=5", "articles_list", None),
        ("GET", "/api/v1/articles?page=1&page_size=10&sort_by=created_at", "articles_sort", None),
        ("GET", "/api/v1/graph/metrics", "graph_metrics", None),
        ("GET", "/api/v1/graph/entities?page=1&page_size=10", "entities_list", None),
        ("GET", "/api/v1/graph/communities", "communities_list", None),
        ("GET", "/api/v1/sources", "sources_list", None),
        ("GET", "/api/v1/alerts/rules", "alert_rules", None),
        ("GET", "/api/v1/briefings?limit=5", "briefings", None),
    ]
    # Per-article detail.
    for aid in REAL_ARTICLE_IDS[:3]:
        plan.append(("GET", f"/api/v1/articles/{aid}", f"article_detail:{aid}", None))
    # Search endpoints.
    for q in REAL_SEARCH_QUERIES:
        plan.append(("GET", f"/api/v1/search?q={q}&mode=local&limit=5", f"search_local:{q}", None))
    for q in REAL_SEARCH_QUERIES[:3]:
        plan.append(
            ("GET", f"/api/v1/search?q={q}&mode=global&limit=5", f"search_global:{q}", None)
        )
    # Entity lookup.
    for name in REAL_ENTITY_NAMES:
        plan.append(("GET", f"/api/v1/graph/entities?name={name}", f"entity_lookup:{name}", None))
    return plan


def run_tests_for_combo(
    base: str, combo: str, plan: list[tuple[str, str, str, dict | None]]
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for idx, (method, path, label, body) in enumerate(plan, 1):
        url = f"{base}{path}"
        code, resp = _request(method, url, body=body)
        results[label] = {
            "endpoint": f"{method} {path}",
            "status_code": code,
            "response": resp,
        }
        # Print progress to stdout (line-buffered) so we can monitor.
        print(f"    [{idx}/{len(plan)}] {label}: {code}", flush=True)
    return results


def compare_combos(
    all_results: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Compare responses across all 4 combos for each endpoint label."""
    inconsistencies: dict[str, list[dict[str, Any]]] = {}
    if not all_results:
        return inconsistencies
    labels = list(next(iter(all_results.values())).keys())
    combos = list(all_results.keys())
    for label in labels:
        per_combo = {c: all_results[c].get(label, {}) for c in combos}
        # Compare status codes first.
        codes = {c: r.get("status_code") for c, r in per_combo.items()}
        if len(set(codes.values())) > 1:
            inconsistencies.setdefault(label, []).append(
                {
                    "type": "status_code_mismatch",
                    "details": codes,
                }
            )
            continue
        # Compare normalized bodies pairwise.
        normed = {c: _normalize(r.get("response")) for c, r in per_combo.items()}
        baseline = combos[0]
        for other in combos[1:]:
            if not _values_equal(normed[baseline], normed[other]):
                inconsistencies.setdefault(label, []).append(
                    {
                        "type": "body_mismatch",
                        "baseline": baseline,
                        "other": other,
                        "baseline_preview": _preview(normed[baseline]),
                        "other_preview": _preview(normed[other]),
                    }
                )
    return inconsistencies


def _preview(obj: Any, limit: int = 800) -> str:
    s = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return s[:limit] + ("..." if len(s) > limit else "")


def main() -> int:
    report_path = Path("specmark/changes/db-consistency-verify/records/api_cross_test.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    print("=== Waiting for all 4 combos to become healthy ===")
    for combo, base in COMBOS.items():
        print(f"  {combo}: ", end="", flush=True)
        if _wait_for_health(base, timeout=420):
            print("healthy")
        else:
            print("UNHEALTHY — will attempt tests anyway")

    plan = build_test_plan()
    print(f"\n=== Running {len(plan)} tests across 4 combos ===")
    all_results: dict[str, dict[str, dict[str, Any]]] = {}
    for combo, base in COMBOS.items():
        print(f"  Testing {combo} ({base}) ...", flush=True)
        all_results[combo] = run_tests_for_combo(base, combo, plan)

    print("\n=== Comparing responses ===")
    inconsistencies = compare_combos(all_results)
    total_inc = sum(len(v) for v in inconsistencies.values())

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "combos": list(COMBOS.keys()),
        "endpoints_tested": len(plan),
        "total_inconsistencies": total_inc,
        "summary": {
            label: (
                "CONSISTENT"
                if label not in inconsistencies
                else f"{len(inconsistencies[label])} ISSUES"
            )
            for label in [p[2] for p in plan]
        },
        "inconsistencies": inconsistencies,
        "raw_results": {
            combo: {
                label: {
                    "endpoint": r["endpoint"],
                    "status_code": r["status_code"],
                    "response_preview": _preview(r["response"], 400),
                }
                for label, r in results.items()
            }
            for combo, results in all_results.items()
        },
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"\n=== Summary ===")
    print(f"  Combos tested: {', '.join(COMBOS.keys())}")
    print(f"  Endpoints tested: {len(plan)}")
    print(f"  Inconsistencies: {total_inc}")
    if total_inc > 0:
        print(f"\n  Inconsistent endpoints:")
        for label, items in inconsistencies.items():
            print(f"    {label}: {len(items)} issue(s)")
    print(f"\n  Full report: {report_path}")
    return 1 if total_inc > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
