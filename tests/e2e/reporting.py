# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Markdown audit report generation for the E2E API suite.

Reads all records captured by :class:`APIResponseRecorder` and produces a
human-reviewable report: per-request request parameters, response status,
business code, and assertion outcome, plus aggregate statistics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.e2e.api_response_recorder import APIResponseRecorder


def generate_audit_report(recorder: APIResponseRecorder, output_path: str | Path) -> Path:
    """Render the full audit report and return its path."""
    lines: list[str] = [
        "# Weaver API E2E 审计报告",
        "",
        "所有请求/响应均由 APIResponseRecorder 落盘（`temp/api_responses/<域>/<场景>_<时间戳>.json`），",
        "本报告为汇总视图，供人工复核。",
        "",
    ]

    records = recorder.records
    by_domain: dict[str, list[dict[str, Any]]] = {}
    by_status: dict[int, int] = {}
    total_duration = 0.0
    error_branches = 0

    for record in records:
        domain = record["metadata"]["endpoint"]
        by_domain.setdefault(domain, []).append(record)
        status = record["response"]["status_code"]
        by_status[status] = by_status.get(status, 0) + 1
        total_duration += record["metadata"]["duration_ms"]
        if status >= 400:
            error_branches += 1

    lines += [
        "## 总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 总请求数 | {len(records)} |",
        f"| 覆盖端点域 | {len(by_domain)} |",
        f"| 非 2xx 响应（容错/异常路径） | {error_branches} |",
        f"| 总耗时 | {total_duration:.1f} ms |",
        "",
        "### 状态码分布",
        "",
        "| 状态码 | 次数 |",
        "|---|---|",
    ]
    for status in sorted(by_status):
        lines.append(f"| {status} | {by_status[status]} |")

    lines += [
        "",
        "### 端点域分布",
        "",
        "| 域 | 请求数 |",
        "|---|---|",
    ]
    for domain in sorted(by_domain):
        lines.append(f"| {domain} | {len(by_domain[domain])} |")

    for domain in sorted(by_domain):
        lines += [
            "",
            f"## 域：{domain}",
            "",
            "| 场景 | 方法 | 路径 | 请求参数 | 状态码 | 业务码 | 耗时(ms) | 断言 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for record in by_domain[domain]:
            meta = record["metadata"]
            req = record["request"]
            resp = record["response"]
            params = _compact(req.get("params")) or _compact(req.get("body")) or "—"
            body = resp.get("body")
            code = body.get("code", "—") if isinstance(body, dict) else "—"
            validation = record.get("validation") or {}
            assertion = "✓" if validation.get("envelope") == "passed" else "✗"
            lines.append(
                f"| {meta['test_case']} | {req['method']} | {_short(req['url'])} "
                f"| {params} | {resp['status_code']} | {code} "
                f"| {meta['duration_ms']} | {assertion} |"
            )

    report_path = Path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _compact(value: Any, limit: int = 80) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _short(url: str, limit: int = 60) -> str:
    return url if len(url) <= limit else url[: limit - 3] + "..."
