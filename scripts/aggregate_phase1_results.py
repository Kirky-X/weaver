#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Aggregate Phase 1 test results from all router subagent _summary.json files.

Handles 6+ different summary structures produced by independent subagents:
  - Structure A: {total, pass|passed, fail|failed, skip|skipped}
  - Structure B: {total_test_cases | total_cases | test_cases_total, passed, failed, skipped}
  - Structure B2: {test_cases_total, test_cases_pass, test_cases_fail, test_cases_skip}
  - Structure C: {endpoints[]: [{test_count, passed, failed, skipped}], summary: {...}}
  - Structure D: {cases[] | test_cases[] | tests[]: [{pass|passed| status}]}
  - Structure E (graph_monitoring): {total_cases, pass, fail, skip, by_category: {...}}

Also falls back to status_code_heuristic for routers without _summary.json,
counting 5xx as fail and other status codes as pass.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PHASE1_DIR = Path("specmark/changes/api-acceptance-test/records/phase1")
OUTPUT_FILE = PHASE1_DIR / "summary.json"


def _first(d: dict, *keys: str) -> int | None:
    """Return first matching key's int value."""
    for k in keys:
        if k in d:
            try:
                return int(d[k])
            except (TypeError, ValueError):
                return None
    return None


def extract_summary(d: dict) -> tuple[int, int, int, int]:
    """Extract (total, pass, fail, skip) from a summary dict.

    Tries multiple field name conventions and nested structures.
    Returns (0, 0, 0, 0) if nothing recognized.
    """
    if not isinstance(d, dict):
        return (0, 0, 0, 0)

    # If has nested 'summary' key, try that first (health uses this pattern)
    if "summary" in d and isinstance(d["summary"], dict):
        nested = extract_summary(d["summary"])
        if nested[0] > 0:
            return nested

    # Structure B2: test_cases_pass / test_cases_fail / test_cases_skip
    # (checked BEFORE Structure A because health's summary has only these fields)
    tcp = _first(
        d,
        "test_cases_pass",
        "cases_passed",
        "tests_passed",
        "test_cases_passed",
    )
    if tcp is not None:
        tct = (
            _first(
                d,
                "test_cases_total",
                "total_test_cases",
                "total_cases",
                "total",
                "total_tests",
            )
            or 0
        )
        tcf = (
            _first(
                d,
                "test_cases_fail",
                "cases_failed",
                "tests_failed",
                "test_cases_failed",
            )
            or 0
        )
        tcs = (
            _first(
                d,
                "test_cases_skip",
                "cases_skipped",
                "tests_skipped",
                "test_cases_skipped",
            )
            or 0
        )
        if tct > 0:
            return (tct, tcp, tcf, tcs)

    # Structure A/B/E: flat counters with various key names
    total = _first(
        d,
        "total",
        "total_cases",
        "total_test_cases",
        "total_tests",
        "test_cases_total",
        "tests_total",
        "count",
    )
    if total is not None and total > 0:
        p = _first(d, "pass", "passed", "passes", "success", "ok") or 0
        f = _first(d, "fail", "failed", "failures", "error", "errors") or 0
        s = _first(d, "skip", "skipped", "skips", "ignored") or 0
        return (total, p, f, s)

    # Structure C: endpoints[] array — sum across endpoints
    endpoints = d.get("endpoints")
    if isinstance(endpoints, list) and endpoints:
        total_sum = pass_sum = fail_sum = skip_sum = 0
        ok = False
        for ep in endpoints:
            if not isinstance(ep, dict):
                continue
            ep_total = _first(ep, "test_count", "total", "tests", "test_cases", "cases")
            ep_pass = _first(ep, "passed", "pass", "success", "ok")
            ep_fail = _first(ep, "failed", "fail", "failures")
            ep_skip = _first(ep, "skipped", "skip", "ignored")
            # If no per-endpoint counters but has test_cases list, count it
            if ep_total is None and "test_cases" in ep and isinstance(ep["test_cases"], list):
                ep_total = len(ep["test_cases"])
                ep_pass = sum(
                    1
                    for c in ep["test_cases"]
                    if isinstance(c, dict)
                    and (
                        c.get("passed") is True
                        or c.get("pass") is True
                        or c.get("result") == "pass"
                        or c.get("status", "").lower() in ("pass", "passed", "ok")
                    )
                )
                ep_fail = sum(
                    1
                    for c in ep["test_cases"]
                    if isinstance(c, dict)
                    and (
                        c.get("passed") is False
                        or c.get("pass") is False
                        or c.get("result") == "fail"
                        or c.get("status", "").lower() in ("fail", "failed")
                    )
                )
            if ep_total is not None:
                total_sum += ep_total
                ok = True
            if ep_pass is not None:
                pass_sum += ep_pass
            if ep_fail is not None:
                fail_sum += ep_fail
            if ep_skip is not None:
                skip_sum += ep_skip
        if ok and total_sum > 0:
            return (total_sum, pass_sum, fail_sum, skip_sum)

    # Structure D: cases[] | test_cases[] | tests[] arrays
    for arr_key in ("cases", "test_cases", "tests", "results"):
        arr = d.get(arr_key)
        if isinstance(arr, list) and arr:
            total_count = len(arr)
            pass_count = sum(
                1
                for c in arr
                if isinstance(c, dict)
                and (
                    c.get("passed") is True
                    or c.get("pass") is True
                    or c.get("result") == "pass"
                    or str(c.get("status", "")).lower() in ("pass", "passed", "ok")
                    or str(c.get("result", "")).lower() in ("pass", "passed", "ok")
                )
            )
            fail_count = sum(
                1
                for c in arr
                if isinstance(c, dict)
                and (
                    c.get("passed") is False
                    or c.get("pass") is False
                    or c.get("result") == "fail"
                    or str(c.get("status", "")).lower() in ("fail", "failed")
                    or str(c.get("result", "")).lower() in ("fail", "failed")
                )
            )
            skip_count = sum(
                1
                for c in arr
                if isinstance(c, dict)
                and (
                    c.get("skipped") is True
                    or c.get("skip") is True
                    or c.get("result") == "skip"
                    or str(c.get("status", "")).lower() in ("skip", "skipped", "ignored")
                    or str(c.get("result", "")).lower() in ("skip", "skipped", "ignored")
                )
            )
            return (total_count, pass_count, fail_count, skip_count)

    return (0, 0, 0, 0)


def status_code_heuristic(router_dir: Path) -> tuple[int, int, int, int]:
    """Fallback: count test JSON files by HTTP status code.

    5xx = fail, 4xx = pass (auth/validation expected), 2xx/3xx = pass.
    """
    total = pass_count = fail_count = skip_count = 0
    for f in router_dir.glob("*.json"):
        if f.name == "_summary.json":
            continue
        # Read file once and cache text for fallback regex search below.
        # Avoids double disk IO + UTF-8 decode when status_code is missing
        # from the parsed dict and we need to scan the raw JSON string.
        try:
            text = f.read_text()
        except OSError:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue

        # Find status code in various locations
        status = None
        if isinstance(data, dict):
            response = data.get("response", {})
            if isinstance(response, dict):
                status = response.get("status_code")
            if status is None:
                status = data.get("status_code") or data.get("actual_status")
            if status is None:
                # Look for nested fields
                for k in ("expected_status", "actual_status"):
                    v = data.get(k)
                    if isinstance(v, int):
                        status = v
                        break
            # Skip flag
            if data.get("skipped") or data.get("skip"):
                total += 1
                skip_count += 1
                continue

        if status is None:
            # Try to find status anywhere in the cached JSON string
            m = re.search(r'"status_code"\s*:\s*(\d+)', text)
            if m:
                status = int(m.group(1))

        if status is None:
            # Truly unknown — skip
            continue

        total += 1
        if status >= 500:
            fail_count += 1
        else:
            pass_count += 1

    return (total, pass_count, fail_count, skip_count)


def aggregate() -> None:
    routers: list[dict] = []
    grand_total = grand_pass = grand_fail = grand_skip = 0

    for router_dir in sorted(PHASE1_DIR.iterdir()):
        if not router_dir.is_dir():
            continue
        summary_file = router_dir / "_summary.json"

        if summary_file.exists():
            try:
                data = json.loads(summary_file.read_text())
            except json.JSONDecodeError:
                data = {}
            total, p, f, s = extract_summary(data)
            method = "subagent_summary"
            if total == 0:
                # Fallback to heuristic
                total, p, f, s = status_code_heuristic(router_dir)
                method = "status_code_heuristic (fallback)"
        else:
            total, p, f, s = status_code_heuristic(router_dir)
            method = "status_code_heuristic"

        routers.append(
            {
                "router": router_dir.name,
                "total": total,
                "pass": p,
                "fail": f,
                "skip": s,
                "method": method,
            }
        )
        grand_total += total
        grand_pass += p
        grand_fail += f
        grand_skip += s

    pass_rate = (grand_pass / grand_total * 100) if grand_total > 0 else 0.0

    summary = {
        "phase": "Phase 1 (PG + Neo4j + Redis)",
        "generated_at": datetime.now().isoformat(),
        "routers_tested": len(routers),
        "totals": {
            "total": grand_total,
            "pass": grand_pass,
            "fail": grand_fail,
            "skip": grand_skip,
            "pass_rate_percent": round(pass_rate, 2),
        },
        "routers": routers,
        "high_severity_findings": [
            {
                "id": "F-001",
                "severity": "HIGH",
                "router": "health",
                "issue": (
                    "路由冲突：src/api/endpoints/system.py:130 与 src/api/endpoints/health.py:264 都注册 /api/v1/health/dependencies"
                ),
                "impact": (
                    "system_router 在 health_router 之前注册，覆盖 health_router 的 /health/dependencies 端点"
                ),
                "fix_required": "调整 router 注册顺序或重命名端点（用户禁止修改路由文件，待确认）",
            },
            {
                "id": "F-002",
                "severity": "MEDIUM",
                "router": "analytics",
                "issue": "briefings date 查询 bug：PG 有数据但 API 返回空列表",
                "impact": "用户按日期查询 briefings 时无法获取数据",
                "fix_required": "检查 analytics briefings date 端点的 SQL 查询条件和时区处理",
            },
            {
                "id": "F-003",
                "severity": "LOW",
                "router": "analytics",
                "issue": "briefings date 参数缺 pattern 校验，接受任意字符串",
                "impact": "可能触发数据库异常或 SQL 注入风险（参数化查询已防注入但用户体验差）",
                "fix_required": "添加 YYYY-MM-DD 格式校验",
            },
            {
                "id": "F-004",
                "severity": "LOW",
                "router": "alerts",
                "issue": "threshold 字段无业务范围校验，接受负数和超大值",
                "impact": "可能创建无效 alert rule",
                "fix_required": "添加 0-1 范围校验",
            },
            {
                "id": "F-005",
                "severity": "LOW",
                "router": "llm",
                "issue": "usage summary error_types 字段始终为空数组",
                "impact": "用户无法查看 LLM 错误类型分布",
                "fix_required": "检查 llm_usage_hourly 聚合查询是否包含 error_type 字段",
            },
            {
                "id": "F-006",
                "severity": "LOW",
                "router": "saga",
                "issue": "retry/compensate 无状态前置检查",
                "impact": "可对已 completed 的 saga 执行 retry，产生副作用",
                "fix_required": "添加 saga.status 前置检查",
            },
        ],
    }

    OUTPUT_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    # Print table
    print(f"\n{'Router':<25} {'Total':>7} {'Pass':>7} {'Fail':>7} {'Skip':>7}  Method")
    print("-" * 75)
    for r in routers:
        print(
            f"{r['router']:<25} {r['total']:>7} {r['pass']:>7} {r['fail']:>7} {r['skip']:>7}  {r['method']}"
        )
    print("-" * 75)
    print(f"{'TOTAL':<25} {grand_total:>7} {grand_pass:>7} {grand_fail:>7} {grand_skip:>7}")
    print(f"Pass rate: {pass_rate:.2f}%")
    print(f"\nSummary written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    aggregate()
