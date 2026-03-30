# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM Usage API 验证脚本 — 探测所有端点并输出请求/响应报告。

用法:
    python tests/scripts/verify_llm_usage_api.py
    python tests/scripts/verify_llm_usage_api.py --output /tmp/report.txt
    python tests/scripts/verify_llm_usage_api.py --skip-pytest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# 确保项目 src 在 path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints import admin
from api.endpoints._deps import Endpoints
from api.middleware.auth import verify_api_key

# ── 常量 ────────────────────────────────────────────────────────

DEFAULT_FROM = "2024-01-01T00:00:00Z"
DEFAULT_TO = "2024-01-31T23:59:59Z"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "llm_usage_api_report.txt"
SEPARATOR = "=" * 80
THIN_SEP = "-" * 60

# ── Mock Data Factory ───────────────────────────────────────────


def _build_normal_data() -> dict[str, Any]:
    """正常场景：多行丰富数据。"""
    return {
        "query_hourly": [
            {
                "time_bucket": "2024-01-15T10:00:00",
                "call_count": 100,
                "input_tokens_sum": 50000,
                "output_tokens_sum": 25000,
                "total_tokens_sum": 75000,
                "latency_avg_ms": 500.5,
                "latency_min_ms": 200.0,
                "latency_max_ms": 1500.0,
                "success_count": 98,
                "failure_count": 2,
            },
            {
                "time_bucket": "2024-01-15T11:00:00",
                "call_count": 85,
                "input_tokens_sum": 42000,
                "output_tokens_sum": 21000,
                "total_tokens_sum": 63000,
                "latency_avg_ms": 480.2,
                "latency_min_ms": 180.0,
                "latency_max_ms": 1200.0,
                "success_count": 84,
                "failure_count": 1,
            },
            {
                "time_bucket": "2024-01-15T12:00:00",
                "call_count": 120,
                "input_tokens_sum": 60000,
                "output_tokens_sum": 30000,
                "total_tokens_sum": 90000,
                "latency_avg_ms": 520.8,
                "latency_min_ms": 150.0,
                "latency_max_ms": 1800.0,
                "success_count": 118,
                "failure_count": 2,
            },
        ],
        "get_summary": {
            "total_calls": 305,
            "total_input_tokens": 152000,
            "total_output_tokens": 76000,
            "total_tokens": 228000,
            "avg_latency_ms": 500.5,
            "max_latency_ms": 1800.0,
            "min_latency_ms": 150.0,
            "success_rate": 0.9836,
            "error_types": {"timeout": 3, "rate_limit": 2},
        },
        "get_by_provider": [
            {
                "provider": "anthropic",
                "call_count": 180,
                "total_tokens": 135000,
                "avg_latency_ms": 480.0,
                "success_rate": 0.99,
            },
            {
                "provider": "aiping",
                "call_count": 125,
                "total_tokens": 93000,
                "avg_latency_ms": 520.0,
                "success_rate": 0.97,
            },
        ],
        "get_by_model": [
            {
                "model": "claude-sonnet-4",
                "provider": "anthropic",
                "call_count": 120,
                "total_tokens": 90000,
                "avg_latency_ms": 500.0,
                "success_rate": 0.99,
            },
            {
                "model": "claude-haiku-4",
                "provider": "anthropic",
                "call_count": 60,
                "total_tokens": 45000,
                "avg_latency_ms": 350.0,
                "success_rate": 0.98,
            },
            {
                "model": "qwen-plus",
                "provider": "aiping",
                "call_count": 80,
                "total_tokens": 60000,
                "avg_latency_ms": 550.0,
                "success_rate": 0.96,
            },
        ],
        "get_by_call_point": [
            {
                "call_point": "classifier",
                "call_count": 100,
                "total_tokens": 50000,
                "avg_latency_ms": 300.0,
                "success_rate": 0.99,
            },
            {
                "call_point": "analyzer",
                "call_count": 80,
                "total_tokens": 80000,
                "avg_latency_ms": 600.0,
                "success_rate": 0.98,
            },
            {
                "call_point": "entity_extractor",
                "call_count": 125,
                "total_tokens": 98000,
                "avg_latency_ms": 450.0,
                "success_rate": 0.97,
            },
        ],
    }


def _build_empty_data() -> dict[str, Any]:
    """空数据场景。"""
    return {
        "query_hourly": [],
        "get_summary": {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "max_latency_ms": 0.0,
            "min_latency_ms": 0.0,
            "success_rate": 1.0,
            "error_types": {},
        },
        "get_by_provider": [],
        "get_by_model": [],
        "get_by_call_point": [],
    }


def _build_edge_data() -> dict[str, Any]:
    """边界场景：单条极端值数据。"""
    return {
        "query_hourly": [
            {
                "time_bucket": "2024-01-01T00:00:00",
                "call_count": 1,
                "input_tokens_sum": 1,
                "output_tokens_sum": 0,
                "total_tokens_sum": 1,
                "latency_avg_ms": 0.01,
                "latency_min_ms": 0.01,
                "latency_max_ms": 0.01,
                "success_count": 1,
                "failure_count": 0,
            }
        ],
        "get_summary": {
            "total_calls": 1,
            "total_input_tokens": 1,
            "total_output_tokens": 0,
            "total_tokens": 1,
            "avg_latency_ms": 0.01,
            "max_latency_ms": 0.01,
            "min_latency_ms": 0.01,
            "success_rate": 1.0,
            "error_types": {},
        },
        "get_by_provider": [
            {
                "provider": "test",
                "call_count": 1,
                "total_tokens": 1,
                "avg_latency_ms": 0.01,
                "success_rate": 1.0,
            }
        ],
        "get_by_model": [
            {
                "model": "test-model",
                "provider": "test",
                "call_count": 1,
                "total_tokens": 1,
                "avg_latency_ms": 0.01,
                "success_rate": 1.0,
            }
        ],
        "get_by_call_point": [
            {
                "call_point": "test_point",
                "call_count": 1,
                "total_tokens": 1,
                "avg_latency_ms": 0.01,
                "success_rate": 1.0,
            }
        ],
    }


def build_mock_repo(data: dict[str, Any]) -> MagicMock:
    """根据数据场景构建 mock LLMUsageRepo。"""
    repo = MagicMock()
    repo.query_hourly = AsyncMock(return_value=data["query_hourly"])
    repo.get_summary = AsyncMock(return_value=data["get_summary"])
    repo.get_by_provider = AsyncMock(return_value=data["get_by_provider"])
    repo.get_by_model = AsyncMock(return_value=data["get_by_model"])
    repo.get_by_call_point = AsyncMock(return_value=data["get_by_call_point"])
    return repo


# ── TestClient Builder ──────────────────────────────────────────


def build_client(
    data: dict[str, Any],
    with_auth: bool = True,
) -> TestClient:
    """创建 TestClient 实例，注入 mock repo 和可选认证绕过。"""
    mock_repo = build_mock_repo(data)
    Endpoints._llm_usage_repo = mock_repo

    app = FastAPI()
    if with_auth:
        app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    app.include_router(admin.router)

    return TestClient(app)


# ── Probe 定义 ──────────────────────────────────────────────────

ProbeResult = dict[str, Any]


def _probe(
    client: TestClient,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
    description: str = "",
) -> ProbeResult:
    """执行单个端点探测并返回结果。"""
    start = time.monotonic()
    response = client.request(method, url, params=params, headers=headers)
    elapsed_ms = (time.monotonic() - start) * 1000

    try:
        body = response.json()
    except Exception:
        body = response.text

    passed = response.status_code == expected_status

    return {
        "description": description,
        "method": method,
        "url": url,
        "params": params or {},
        "headers": headers or {},
        "expected_status": expected_status,
        "actual_status": response.status_code,
        "elapsed_ms": round(elapsed_ms, 1),
        "body": body,
        "passed": passed,
    }


def run_all_probes() -> list[ProbeResult]:
    """运行全部 15 个端点探测。"""
    results: list[ProbeResult] = []
    normal = _build_normal_data()
    empty = _build_empty_data()

    # ── Probe 1-6: GET /admin/llm-usage 正常/筛选/空数据 ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                description="#1 GET /admin/llm-usage (默认 hourly 粒度)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO, "granularity": "daily"},
                description="#2 GET /admin/llm-usage (daily 粒度)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO, "granularity": "monthly"},
                description="#3 GET /admin/llm-usage (monthly 粒度)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO, "provider": "anthropic"},
                description="#4 GET /admin/llm-usage (provider=anthropic)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={
                    "from": DEFAULT_FROM,
                    "to": DEFAULT_TO,
                    "model": "claude-sonnet-4",
                    "llm_type": "chat",
                    "call_point": "classifier",
                },
                description="#5 GET /admin/llm-usage (多筛选: model+llm_type+call_point)",
            )
        )

    with build_client(empty) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                description="#6 GET /admin/llm-usage (空数据范围)",
            )
        )

    # ── Probe 7-9: 参数验证错误 (422) ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"to": DEFAULT_TO},
                expected_status=422,
                description="#7 GET /admin/llm-usage (缺少 from 参数, 预期 422)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM},
                expected_status=422,
                description="#8 GET /admin/llm-usage (缺少 to 参数, 预期 422)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO, "granularity": "invalid"},
                expected_status=422,
                description="#9 GET /admin/llm-usage (granularity=invalid, 预期 422)",
            )
        )

    # ── Probe 10-11: GET /admin/llm-usage/summary ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage/summary",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                description="#10 GET /admin/llm-usage/summary (基础查询)",
            )
        )

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage/summary",
                params={
                    "from": DEFAULT_FROM,
                    "to": DEFAULT_TO,
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                },
                description="#11 GET /admin/llm-usage/summary (带筛选: provider+model)",
            )
        )

    # ── Probe 12: GET /admin/llm-usage/by-provider ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage/by-provider",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                description="#12 GET /admin/llm-usage/by-provider (基础查询)",
            )
        )

    # ── Probe 13: GET /admin/llm-usage/by-model ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage/by-model",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO, "provider": "anthropic"},
                description="#13 GET /admin/llm-usage/by-model (provider 筛选)",
            )
        )

    # ── Probe 14: GET /admin/llm-usage/by-call-point ──

    with build_client(normal) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage/by-call-point",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                description="#14 GET /admin/llm-usage/by-call-point (基础查询)",
            )
        )

    # ── Probe 15: 无认证访问 ──

    with build_client(normal, with_auth=False) as c:
        results.append(
            _probe(
                c,
                "GET",
                "/admin/llm-usage",
                params={"from": DEFAULT_FROM, "to": DEFAULT_TO},
                expected_status=401,
                description="#15 GET /admin/llm-usage (无认证, 预期 401)",
            )
        )

    return results


# ── 报告生成 ────────────────────────────────────────────────────


def format_probe_report(probe: ProbeResult) -> str:
    """格式化单个探测结果。"""
    lines: list[str] = []
    lines.append(f"--- {probe['description']} ---")
    lines.append("")
    lines.append("请求:")
    lines.append(f"  方法: {probe['method']}")
    lines.append(f"  URL: {probe['url']}")

    if probe["params"]:
        lines.append("  参数:")
        for k, v in probe["params"].items():
            lines.append(f"    {k} = {v}")

    if probe["headers"]:
        lines.append("  自定义请求头:")
        for k, v in probe["headers"].items():
            masked = v[:8] + "***" if len(v) > 8 else "***"
            lines.append(f"    {k}: {masked}")

    lines.append("")
    lines.append("响应:")
    lines.append(f"  状态码: {probe['actual_status']}")
    lines.append(f"  预期状态码: {probe['expected_status']}")
    lines.append(f"  延迟: {probe['elapsed_ms']}ms")

    body = probe["body"]
    if isinstance(body, (dict, list)):
        body_str = json.dumps(body, indent=4, ensure_ascii=False)
        # 缩进 body
        indented = "\n".join("    " + line for line in body_str.splitlines())
        lines.append("  Body:")
        lines.append(indented)
    else:
        lines.append(f"  Body: {body}")

    status = "PASS" if probe["passed"] else "FAIL"
    icon = "OK" if probe["passed"] else "XX"
    lines.append("")
    lines.append(f"结果: {status} [{icon}]")
    lines.append("")
    return "\n".join(lines)


def run_pytest_tests() -> tuple[str, int]:
    """运行 LLM usage 相关的 pytest 测试，返回 (output, exit_code)。"""
    test_files = [
        "tests/unit/test_llm_usage_api.py",
        "tests/unit/test_llm_usage_repo.py",
        "tests/unit/test_llm_usage_buffer.py",
        "tests/unit/test_llm_usage_aggregator.py",
        "tests/unit/test_llm_usage_event_publish.py",
        "tests/integration/test_llm_usage_pipeline.py",
    ]

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *test_files,
        "-v",
        "--tb=short",
        "--no-header",
        "-m",
        "not e2e",
        "--override-ini=addopts=",
    ]

    # Use shell=False for security (command is hardcoded)
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
        timeout=300,
        check=False,  # We handle the return code ourselves
    )

    output = result.stdout
    if result.stderr:
        output += "\n--- STDERR ---\n" + result.stderr

    return output, result.returncode


def generate_report(
    probes: list[ProbeResult],
    pytest_output: str | None,
    pytest_exit_code: int | None,
) -> str:
    """生成完整报告。"""
    lines: list[str] = []

    lines.append(SEPARATOR)
    lines.append("LLM Usage API 验证报告")
    lines.append(f"生成时间: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(SEPARATOR)
    lines.append("")

    # 第一部分: Endpoint Probe
    lines.append("第一部分: Endpoint Probe (15 个端点探测)")
    lines.append(SEPARATOR)

    for probe in probes:
        lines.append(format_probe_report(probe))

    probe_pass = sum(1 for p in probes if p["passed"])
    probe_total = len(probes)
    lines.append(SEPARATOR)
    lines.append(f"Endpoint Probe 汇总: {probe_pass}/{probe_total} PASS")
    lines.append("")

    # 第二部分: Pytest 测试结果
    if pytest_output is not None:
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("第二部分: Pytest 测试结果")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append(pytest_output)
        lines.append("")

        # 解析 pytest 输出中的 passed/failed 数
        pytest_status = "PASS" if pytest_exit_code == 0 else "FAIL"
        lines.append(SEPARATOR)
        lines.append(f"Pytest 退出码: {pytest_exit_code} ({pytest_status})")
        lines.append("")

    # 第三部分: 总结
    lines.append("")
    lines.append(SEPARATOR)
    lines.append("第三部分: 总结")
    lines.append(SEPARATOR)
    lines.append("")
    lines.append(f"  Endpoint Probes: {probe_pass}/{probe_total} PASS")

    if pytest_output is not None:
        lines.append(
            f"  Pytest: {'PASS' if pytest_exit_code == 0 else 'FAIL'} (exit code {pytest_exit_code})"
        )
        overall = "PASS" if (probe_pass == probe_total and pytest_exit_code == 0) else "FAIL"
    else:
        lines.append("  Pytest: SKIPPED (--skip-pytest)")
        overall = "PASS" if probe_pass == probe_total else "FAIL"

    lines.append(f"  总体结果: {overall}")
    lines.append("")

    return "\n".join(lines)


# ── 主入口 ──────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Usage API 验证脚本")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"报告输出路径 (默认: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="跳过 pytest 测试运行",
    )
    args = parser.parse_args()

    print("LLM Usage API 验证脚本")
    print("=" * 40)
    print()

    # 运行 Endpoint Probe
    print("[1/2] 运行 Endpoint Probe (15 个)...")
    probes = run_all_probes()
    probe_pass = sum(1 for p in probes if p["passed"])
    print(f"       完成: {probe_pass}/{len(probes)} PASS")
    print()

    # 运行 Pytest
    pytest_output: str | None = None
    pytest_exit_code: int | None = None

    if not args.skip_pytest:
        print("[2/2] 运行 Pytest 测试 (6 个文件)...")
        pytest_output, pytest_exit_code = run_pytest_tests()
        status = "PASS" if pytest_exit_code == 0 else "FAIL"
        print(f"       完成: {status} (exit code {pytest_exit_code})")
    else:
        print("[2/2] 跳过 Pytest (--skip-pytest)")

    print()

    # 生成报告
    report = generate_report(probes, pytest_output, pytest_exit_code)

    # 写入文件
    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"报告已写入: {output_path}")
    print()

    # 打印简要摘要
    probe_pass = sum(1 for p in probes if p["passed"])
    if probe_pass < len(probes):
        print("失败的 Probe:")
        for p in probes:
            if not p["passed"]:
                print(
                    f"  - {p['description']}: 预期 {p['expected_status']}, 实际 {p['actual_status']}"
                )
        print()

    if pytest_output is not None and pytest_exit_code != 0:
        print("Pytest 测试有失败，请查看报告详情。")
        print()

    # 退出码
    overall_pass = probe_pass == len(probes)
    if pytest_exit_code is not None:
        overall_pass = overall_pass and pytest_exit_code == 0

    if overall_pass:
        print("全部验证通过!")
    else:
        print("存在失败项，请查看报告。")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
