#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Aggregate Phase 1/2 test results from router subagent _summary.json files.

Merges the former ``aggregate_phase1_results.py`` and
``aggregate_phase2_results.py`` into a single script driven by ``--phase``.

Handles 6+ different summary structures produced by independent subagents:
  - Structure A: {total, pass|passed, fail|failed, skip|skipped}
  - Structure B: {total_test_cases | total_cases | test_cases_total, passed, failed, skipped}
  - Structure B2: {test_cases_total, test_cases_pass, test_cases_fail, test_cases_skip}
  - Structure C: {endpoints[]: [{test_count, passed, failed, skipped}], summary: {...}}
  - Structure D: {cases[] | test_cases[] | tests[]: [{pass|passed| status}]}
  - Structure E (graph_monitoring): {total_cases, pass, fail, skip, by_category: {...}}

Also falls back to status_code_heuristic for routers without _summary.json,
counting 5xx as fail and other status codes as pass.

Usage:
    uv run scripts/aggregate_results.py --phase 1
    uv run scripts/aggregate_results.py --phase 2
    uv run scripts/aggregate_results.py --phase all    # both phases (default)
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

_BASE = Path("specmark/changes/api-acceptance-test/records")

# Per-phase configuration: directory, human label, and the historical
# high-severity findings recorded during that phase's acceptance run.
# These are immutable audit records — they document what was found on the
# day the phase executed, so they are kept verbatim rather than regenerated.
_PHASE_CONFIG: dict[int, dict] = {
    1: {
        "dir": _BASE / "phase1",
        "label": "Phase 1 (PG + Neo4j + Redis)",
        "findings": [
            {
                "id": "F-001",
                "severity": "HIGH",
                "router": "health",
                "issue": (
                    "路由冲突：src/api/endpoints/system.py:130 与 "
                    "src/api/endpoints/health.py:264 都注册 /api/v1/health/dependencies"
                ),
                "impact": (
                    "system_router 在 health_router 之前注册，覆盖 health_router 的 "
                    "/health/dependencies 端点"
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
    },
    2: {
        "dir": _BASE / "phase2",
        "label": "Phase 2 (DuckDB + LadybugDB fallback)",
        "test_date": "2026-07-19",
        "findings": [
            {
                "id": "F-007",
                "severity": "HIGH",
                "router": "admin",
                "issue": (
                    "DuckDB api_keys 表自增序列未正确推进，POST /api/v1/admin/api-keys "
                    "报 Duplicate key 'id: N' violates primary key constraint"
                ),
                "impact": "DuckDB fallback 模式下无法创建新 API key（2 个测试用例失败）",
                "root_cause": "DuckDB 序列在 PG→DuckDB 数据导入后未重置为 max(id)+1",
                "fix_required": "导入完成后执行 sequence reset；或在 schema 初始化时重置序列",
            },
            {
                "id": "F-008",
                "severity": "HIGH",
                "router": "alerts",
                "issue": (
                    "DuckDB alert_events 表缺少 payload_hash 列，"
                    "迁移 33_add_alert_events_payload_hash.py 未同步到 duckdb_schema.py"
                ),
                "impact": "DuckDB fallback 模式下 alert_events 写入失败（4 个测试用例失败）",
                "root_cause": "schema drift — PG 迁移未镜像到 DuckDB schema 定义",
                "fix_required": (
                    "在 src/core/db/duckdb_schema.py 中为 alert_events 表添加 payload_hash 列"
                ),
            },
            {
                "id": "F-009",
                "severity": "LOW",
                "router": "communities_monitoring",
                "issue": "trailing slash 307 重定向（curl 默认不跟随，需 --location）",
                "impact": "测试 harness 差异，非服务器 bug",
                "root_cause": (
                    "curl 默认 follow_redirects=False，Phase 1 用 requests 库默认 "
                    "follow_redirects=True"
                ),
                "fix_required": "统一测试脚本使用 --location 或在客户端层处理重定向",
            },
        ],
    },
}


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


def aggregate(phase: int) -> None:
    """Aggregate results for a single phase and write summary.json."""
    cfg = _PHASE_CONFIG[phase]
    phase_dir: Path = cfg["dir"]
    output_file = phase_dir / "summary.json"

    if not phase_dir.exists():
        print(f"Phase {phase} directory not found: {phase_dir}")
        return

    routers: list[dict] = []
    grand_total = grand_pass = grand_fail = grand_skip = 0

    for router_dir in sorted(phase_dir.iterdir()):
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

    summary: dict = {
        "phase": cfg["label"],
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
        "high_severity_findings": cfg["findings"],
    }
    if "test_date" in cfg:
        summary["test_date"] = cfg["test_date"]

    output_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    # Print table — width adapts to longest router name for readability.
    col = max((len(r["router"]) for r in routers), default=10)
    col = max(col, 10) + 2
    header = f"{'Router':<{col}} {'Total':>7} {'Pass':>7} {'Fail':>7} {'Skip':>7}  Method"
    sep = "-" * (len(header) + 10)
    print(f"\n=== Phase {phase} ({cfg['label']}) ===")
    print(header)
    print(sep)
    for r in routers:
        print(
            f"{r['router']:<{col}} {r['total']:>7} {r['pass']:>7} {r['fail']:>7} {r['skip']:>7}  {r['method']}"
        )
    print(sep)
    print(f"{'TOTAL':<{col}} {grand_total:>7} {grand_pass:>7} {grand_fail:>7} {grand_skip:>7}")
    print(f"Pass rate: {pass_rate:.2f}%")
    print(f"Summary written to: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate Phase 1/2 test results.")
    parser.add_argument(
        "--phase",
        choices=("1", "2", "all"),
        default="all",
        help="Phase to aggregate (default: all = both phases).",
    )
    args = parser.parse_args()

    phases = [1, 2] if args.phase == "all" else [int(args.phase)]
    for ph in phases:
        aggregate(ph)


if __name__ == "__main__":
    main()
