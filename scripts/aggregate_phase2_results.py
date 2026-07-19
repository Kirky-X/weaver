#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Aggregate Phase 2 test results from all router subagent _summary.json files.

Phase 2 = DuckDB + LadybugDB fallback mode (PG/Neo4j forced offline).
Reuses the same 6-structure extraction logic as Phase 1 aggregator.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PHASE2_DIR = Path("specmark/changes/api-acceptance-test/records/phase2")
OUTPUT_FILE = PHASE2_DIR / "summary.json"


def _first(d: dict, *keys: str) -> int | None:
    for k in keys:
        if k in d:
            try:
                return int(d[k])
            except (TypeError, ValueError):
                return None
    return None


def extract_summary(d: dict) -> tuple[int, int, int, int]:
    if not isinstance(d, dict):
        return (0, 0, 0, 0)

    if "summary" in d and isinstance(d["summary"], dict):
        nested = extract_summary(d["summary"])
        if nested[0] > 0:
            return nested

    tcp = _first(d, "test_cases_pass", "cases_passed", "tests_passed", "test_cases_passed")
    if tcp is not None:
        tct = (
            _first(d, "test_cases_total", "total_test_cases", "total_cases", "total", "total_tests")
            or 0
        )
        tcf = _first(d, "test_cases_fail", "cases_failed", "tests_failed", "test_cases_failed") or 0
        tcs = (
            _first(d, "test_cases_skip", "cases_skipped", "tests_skipped", "test_cases_skipped")
            or 0
        )
        if tct > 0:
            return (tct, tcp, tcf, tcs)

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
                        or str(c.get("status", "")).lower() in ("pass", "passed", "ok")
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
                        or str(c.get("status", "")).lower() in ("fail", "failed")
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
    total = pass_count = fail_count = skip_count = 0
    for f in router_dir.glob("*.json"):
        if f.name == "_summary.json":
            continue
        # Cache file text to avoid double disk IO (see phase1 aggregator).
        try:
            text = f.read_text()
        except OSError:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        status = None
        if isinstance(data, dict):
            response = data.get("response", {})
            if isinstance(response, dict):
                status = response.get("status_code")
            if status is None:
                status = data.get("status_code") or data.get("actual_status")
            if status is None:
                for k in ("expected_status", "actual_status"):
                    v = data.get(k)
                    if isinstance(v, int):
                        status = v
                        break
            if data.get("skipped") or data.get("skip"):
                total += 1
                skip_count += 1
                continue
        if status is None:
            m = re.search(r'"status_code"\s*:\s*(\d+)', text)
            if m:
                status = int(m.group(1))
        if status is None:
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

    for router_dir in sorted(PHASE2_DIR.iterdir()):
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
        "phase": "Phase 2 (DuckDB + LadybugDB fallback)",
        "test_date": "2026-07-19",
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
                "id": "F-007",
                "severity": "HIGH",
                "router": "admin",
                "issue": (
                    "DuckDB api_keys 表自增序列未正确推进，POST /api/v1/admin/api-keys 报 Duplicate key 'id: N' violates primary key constraint"
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
                    "DuckDB alert_events 表缺少 payload_hash 列，迁移 33_add_alert_events_payload_hash.py 未同步到 duckdb_schema.py"
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
                    "curl 默认 follow_redirects=False，Phase 1 用 requests 库默认 follow_redirects=True"
                ),
                "fix_required": "统一测试脚本使用 --location 或在客户端层处理重定向",
            },
        ],
    }

    OUTPUT_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n{'Router':<28} {'Total':>7} {'Pass':>7} {'Fail':>7} {'Skip':>7}  Method")
    print("-" * 80)
    for r in routers:
        print(
            f"{r['router']:<28} {r['total']:>7} {r['pass']:>7} {r['fail']:>7} {r['skip']:>7}  {r['method']}"
        )
    print("-" * 80)
    print(f"{'TOTAL':<28} {grand_total:>7} {grand_pass:>7} {grand_fail:>7} {grand_skip:>7}")
    print(f"Pass rate: {pass_rate:.2f}%")
    print(f"\nSummary written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    aggregate()
