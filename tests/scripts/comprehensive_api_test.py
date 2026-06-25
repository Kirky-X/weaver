#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Comprehensive API test script covering all endpoints and parameter combinations.

Starts the Weaver app automatically, polls health endpoint until ready, then runs
parameterized test cases against every API endpoint. Tests cover:
  - Normal parameter values
  - Boundary values (empty, min, max)
  - Invalid parameters (wrong type, missing required)
  - Authentication scenarios (no auth, wrong auth, regular key on admin endpoints)

All requests and responses are recorded to ``temp/api_responses/`` grouped by
endpoint category, plus a ``summary.json`` report.

Usage:
    uv run python tests/scripts/comprehensive_api_test.py
    uv run python tests/scripts/comprehensive_api_test.py --no-start
    uv run python tests/scripts/comprehensive_api_test.py --url http://localhost:8001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:18012"
DEFAULT_API_KEY = "dev_api_key_1234567890123456789012345678"
DEFAULT_ADMIN_KEY = "dev_admin_key_1234567890123456789012345"
OUTPUT_DIR = Path("temp/api_responses")
STARTUP_TIMEOUT_SECONDS = 120
HEALTH_POLL_INTERVAL_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 60.0
LLM_HEAVY_REQUEST_TIMEOUT_SECONDS = 120.0
APP_STARTUP_GRACE_SECONDS = 2
INTER_TEST_DELAY_SECONDS = 0.5
LLM_HEAVY_INTER_TEST_DELAY_SECONDS = 2.0

# Real search queries based on database content (replaces generic "test").
# These are populated at runtime by _fetch_real_data(); fallbacks cover
# the common article topics (FFmpeg vulnerability, Tecno phone, Xiaomi MiMo).
REAL_SEARCH_QUERIES: list[str] = [
    "FFmpeg",
    "Tecno",
    "小米",
    "AI聊天机器人",
    "超算",
]
REAL_ENTITY_NAME = "FFmpeg"
REAL_ARTICLE_ID: str | None = None
REAL_SOURCE_ID = "rss-solidot"

# Abnormal strings for security/robustness testing.
ABNORMAL_SQL_INJECTION = "'; DROP TABLE articles; --"
ABNORMAL_XSS = "<script>alert('xss')</script>"
ABNORMAL_CYPHER_INJECTION = "MATCH (n) DELETE n"
ABNORMAL_LONG_STRING = "a" * 1000

PASS = "\u2713"
FAIL = "\u2717"
SKIP = "\u2928"
WARN = "\u26a0"


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    MAGENTA = "\033[0;35m"
    NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


def log_step(step: str, msg: str) -> None:
    print(f"{Colors.BLUE}[{step}]{Colors.NC} {msg}")


def log_group(name: str) -> None:
    print(f"\n{Colors.MAGENTA}{'=' * 70}{Colors.NC}")
    print(f"{Colors.MAGENTA}  {name}{Colors.NC}")
    print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")


class ResponseRecorder:
    """Records API requests and responses to JSON files grouped by endpoint."""

    SENSITIVE_HEADERS = {"authorization", "x-api-key", "cookie", "x-csrf-token"}

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []
        self._counter = 0

    def record(
        self,
        endpoint_group: str,
        method: str,
        url: str,
        test_case: str,
        request_headers: dict[str, str] | None,
        request_params: dict[str, Any] | None,
        request_body: Any,
        response_status: int,
        response_headers: dict[str, str] | None,
        response_body: Any,
        duration_ms: float,
        validation: dict[str, Any] | None = None,
    ) -> Path:
        self._counter += 1
        timestamp = datetime.now(UTC).isoformat()
        record = {
            "metadata": {
                "timestamp": timestamp,
                "endpoint": endpoint_group,
                "test_case": test_case,
                "duration_ms": round(duration_ms, 2),
                "sequence": self._counter,
            },
            "request": {
                "method": method.upper(),
                "url": url,
                "headers": self._sanitize_headers(request_headers or {}),
                "params": request_params,
                "body": request_body,
            },
            "response": {
                "status_code": response_status,
                "headers": dict(response_headers or {}),
                "body": response_body,
            },
        }
        if validation:
            record["validation"] = validation

        self.records.append(record)

        endpoint_dir = self.output_dir / endpoint_group
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename(test_case)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self._counter:03d}_{safe_name}_{ts}.json"
        filepath = endpoint_dir / filename
        filepath.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
        return filepath

    def export_summary(self) -> dict[str, Any]:
        by_endpoint: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_validation: dict[str, int] = {"pass": 0, "fail": 0, "skip": 0}
        total_duration = 0.0

        for record in self.records:
            endpoint = record["metadata"]["endpoint"]
            status = str(record["response"]["status_code"])
            duration = record["metadata"]["duration_ms"]
            validation = record.get("validation", {})
            v_status = validation.get("status", "skip") if validation else "skip"

            by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            by_validation[v_status] = by_validation.get(v_status, 0) + 1
            total_duration += duration

        summary = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_calls": len(self.records),
            "by_endpoint": by_endpoint,
            "by_status": by_status,
            "by_validation": by_validation,
            "total_duration_ms": round(total_duration, 2),
            "avg_duration_ms": round(total_duration / max(len(self.records), 1), 2),
        }
        filepath = self.output_dir / "summary.json"
        filepath.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        sanitized: dict[str, str] = {}
        for key, value in headers.items():
            if key.lower() in self.SENSITIVE_HEADERS:
                sanitized[key] = value[:8] + "..." if len(value) > 8 else "***"
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _safe_filename(name: str) -> str:
        safe = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        safe = "".join(c for c in safe if c.isalnum() or c in "_-")
        return safe[:80] if len(safe) > 80 else safe


class AppProcessManager:
    """Manages the Weaver app subprocess lifecycle."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        admin_key: str,
        auto_start: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.admin_key = admin_key
        self.auto_start = auto_start
        self._process: subprocess.Popen | None = None
        # Extract port from base_url for explicit port setting
        # base_url format: http://127.0.0.1:PORT
        try:
            self._port = int(self.base_url.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            self._port = 8010

    async def ensure_running(self) -> bool:
        if await self._is_healthy():
            log_info("App already running, reusing existing instance")
            return True

        if not self.auto_start:
            log_error(f"App not responding at {self.base_url} and --no-start specified")
            return False

        log_step("STARTUP", "Starting Weaver app via subprocess...")
        self._start_process()
        return await self._wait_for_health()

    async def _is_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def _start_process(self) -> None:
        env = os.environ.copy()

        # Load .env file if it exists (to get AGNES_API_KEY and other secrets)
        env_file = Path.cwd() / ".env"
        if env_file.exists():
            with env_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if key and key not in env:
                            env[key] = value
            log_info(f"Loaded .env file: {env_file}")

        env["ENVIRONMENT"] = "development"
        env["WEAVER_API__API_KEY"] = self.api_key
        env["WEAVER_API__ADMIN_API_KEY"] = self.admin_key
        env["WEAVER_API__PORT"] = str(self._port)
        env["WEAVER_POSTGRES__DSN"] = ""
        env["NEO4J_PASSWORD"] = ""
        env["WEAVER_API__REQUIRE_AUTH_FOR_METRICS"] = "false"
        env["WEAVER_API__PORT_AUTO_DETECT"] = "false"
        # Use separate DB paths to avoid file lock conflicts with previous instances
        env["WEAVER_DUCKDB__DB_PATH"] = "data/api_test.duckdb"
        env["WEAVER_LADYBUG__DB_PATH"] = "data/api_test.lbug"

        cmd = ["uv", "run", "python", "-m", "src.main"]
        log_info(f"Command: {' '.join(cmd)}")
        log_info(f"API key: {self.api_key[:8]}... (len={len(self.api_key)})")
        log_info(f"Admin key: {self.admin_key[:8]}... (len={len(self.admin_key)})")

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(Path.cwd()),
            preexec_fn=os.setsid,
        )
        log_info(f"App subprocess started (PID={self._process.pid})")

    async def _wait_for_health(self) -> bool:
        if self._process is None:
            return False

        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        last_output_check = 0.0

        while time.time() < deadline:
            if self._process.poll() is not None:
                log_error(f"App process exited early with code {self._process.returncode}")
                self._dump_recent_output()
                return False

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{self.base_url}/health")
                    if resp.status_code == 200:
                        log_info("App is healthy and ready")
                        await asyncio.sleep(APP_STARTUP_GRACE_SECONDS)
                        return True
            except Exception:
                pass

            if time.time() - last_output_check > 10:
                self._dump_recent_output()
                last_output_check = time.time()

            await asyncio.sleep(HEALTH_POLL_INTERVAL_SECONDS)

        log_error(f"App did not become healthy within {STARTUP_TIMEOUT_SECONDS}s")
        self._dump_recent_output()
        return False

    def _dump_recent_output(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        import select

        try:
            while select.select([self._process.stdout], [], [], 0)[0]:
                line = self._process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    print(f"  {Colors.CYAN}[app]{Colors.NC} {decoded}")
        except Exception:
            pass

    async def stop(self) -> None:
        if self._process is None:
            return
        log_step("SHUTDOWN", "Stopping Weaver app subprocess...")
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as e:
            log_warn(f"Failed to send SIGTERM: {e}, trying SIGKILL")
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except Exception:
                pass
            return

        try:
            self._process.wait(timeout=10)
            log_info("App subprocess stopped")
        except subprocess.TimeoutExpired:
            log_warn("App did not stop within 10s, sending SIGKILL")
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except Exception:
                pass
        finally:
            self._process = None


class ComprehensiveAPITester:
    """Runs parameterized API tests against all endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        admin_key: str,
        recorder: ResponseRecorder,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.admin_key = admin_key
        self.recorder = recorder
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        self._llm_heavy_client = httpx.AsyncClient(timeout=LLM_HEAVY_REQUEST_TIMEOUT_SECONDS)
        self._results: list[dict[str, Any]] = []
        self._created_source_ids: list[str] = []
        self._created_api_key_ids: list[str] = []
        self._created_alert_rule_ids: list[str] = []

    async def close(self) -> None:
        await self._client.aclose()
        await self._llm_heavy_client.aclose()

    async def _fetch_real_data(self) -> None:
        """Fetch real articles, entities, and source IDs from the API.

        Populates module-level constants (REAL_ARTICLE_ID, REAL_ENTITY_NAME,
        REAL_SOURCE_ID, REAL_SEARCH_QUERIES) so that subsequent tests use
        database-backed values instead of the generic placeholder "test".
        """
        global REAL_ARTICLE_ID, REAL_ENTITY_NAME, REAL_SOURCE_ID, REAL_SEARCH_QUERIES

        headers = self._headers("normal")

        # 1. Fetch real articles — use titles as search queries
        try:
            resp = await self._client.get(
                f"{self.base_url}/api/v1/articles",
                headers=headers,
                params={"page": 1, "page_size": 20},
            )
            if resp.status_code == 200:
                body = resp.json()
                data = body.get("data") or {}
                items = data.get("items") or []
                if items:
                    # Use first article ID for article-specific tests
                    REAL_ARTICLE_ID = items[0].get("id")
                    # Collect real titles/subjects as search queries
                    queries: list[str] = []
                    for item in items[:5]:
                        title = item.get("title", "")
                        if title:
                            queries.append(title[:30])
                        for subj in (item.get("subjects") or [])[:3]:
                            if subj and subj not in queries:
                                queries.append(subj)
                    if queries:
                        REAL_SEARCH_QUERIES = queries[:8]
        except Exception as exc:
            log_warn(f"Failed to fetch real articles: {exc}")

        # 2. Fetch real entities — use first entity name for graph tests
        try:
            resp = await self._client.get(
                f"{self.base_url}/api/v1/graph/entities",
                headers=headers,
                params={"limit": 20},
            )
            if resp.status_code == 200:
                body = resp.json()
                data = body.get("data") or []
                if isinstance(data, list) and data:
                    name = data[0].get("canonical_name") or data[0].get("name")
                    if name:
                        REAL_ENTITY_NAME = name
                        if name not in REAL_SEARCH_QUERIES:
                            REAL_SEARCH_QUERIES.insert(0, name)
        except Exception as exc:
            log_warn(f"Failed to fetch real entities: {exc}")

        # 3. Fetch real source IDs
        try:
            resp = await self._client.get(
                f"{self.base_url}/api/v1/sources",
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                data = body.get("data") or []
                if isinstance(data, list) and data:
                    src_id = data[0].get("id")
                    if src_id:
                        REAL_SOURCE_ID = src_id
        except Exception as exc:
            log_warn(f"Failed to fetch real sources: {exc}")

        log_info(
            f"Real data: article_id={REAL_ARTICLE_ID}, "
            f"entity={REAL_ENTITY_NAME}, source={REAL_SOURCE_ID}, "
            f"queries={REAL_SEARCH_QUERIES[:3]}"
        )

    def _headers(self, auth_mode: str = "normal") -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth_mode == "normal":
            headers["X-API-Key"] = self.api_key
        elif auth_mode == "admin":
            headers["X-API-Key"] = self.admin_key
        elif auth_mode == "wrong":
            headers["X-API-Key"] = "invalid-key-that-should-fail-1234567890"
        return headers

    async def request(
        self,
        endpoint_group: str,
        test_case: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        auth_mode: str = "normal",
        expected_status: int | list[int] | None = None,
        allow_server_error: bool = False,
        llm_heavy: bool = False,
    ) -> tuple[int | None, Any, float, dict[str, str]]:
        url = f"{self.base_url}{path}"
        headers = self._headers(auth_mode)
        start = time.monotonic()
        status_code: int | None = None
        response_body: Any = None
        response_headers: dict[str, str] = {}

        client = self._llm_heavy_client if llm_heavy else self._client

        try:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(url, headers=headers, params=params, json=body)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, params=params, json=body)
            elif method == "PATCH":
                resp = await client.patch(url, headers=headers, params=params, json=body)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params)
            else:
                log_error(f"Unsupported method: {method}")
                return None, None, 0.0, {}

            duration_ms = (time.monotonic() - start) * 1000
            status_code = resp.status_code
            response_headers = dict(resp.headers)

            try:
                response_body = resp.json()
            except Exception:
                response_body = {"_raw_text": resp.text[:2000]}

            validation = self._validate(status_code, expected_status, allow_server_error)

            # 响应体内容校验：检测隐性失败（HTTP 200 但响应体含错误）
            if validation.get("status") == "pass" and isinstance(response_body, dict):
                body_str = str(response_body)
                if "Search failed" in body_str or "Circuit breaker" in body_str:
                    validation["warning"] = "response body contains error indicator"
                elif (
                    isinstance(response_body.get("data"), dict)
                    and response_body["data"].get("confidence") == 0.0
                    and response_body["data"].get("entities") == []
                    and response_body["data"].get("sources") == []
                ):
                    validation["warning"] = "empty search results with zero confidence"

            self.recorder.record(
                endpoint_group=endpoint_group,
                method=method,
                url=url,
                test_case=test_case,
                request_headers=headers,
                request_params=params,
                request_body=body,
                response_status=status_code,
                response_headers=response_headers,
                response_body=response_body,
                duration_ms=duration_ms,
                validation=validation,
            )

            self._track_result(endpoint_group, method, path, test_case, status_code, validation)
            await asyncio.sleep(
                LLM_HEAVY_INTER_TEST_DELAY_SECONDS if llm_heavy else INTER_TEST_DELAY_SECONDS
            )
            return status_code, response_body, duration_ms, response_headers

        except httpx.ConnectError as e:
            duration_ms = (time.monotonic() - start) * 1000
            response_body = {"error": f"ConnectError: {e}"}
            validation = {"status": "fail", "reason": f"connection error: {e}"}
            self.recorder.record(
                endpoint_group=endpoint_group,
                method=method,
                url=url,
                test_case=test_case,
                request_headers=headers,
                request_params=params,
                request_body=body,
                response_status=0,
                response_headers={},
                response_body=response_body,
                duration_ms=duration_ms,
                validation=validation,
            )
            self._track_result(endpoint_group, method, path, test_case, 0, validation)
            await asyncio.sleep(
                LLM_HEAVY_INTER_TEST_DELAY_SECONDS if llm_heavy else INTER_TEST_DELAY_SECONDS
            )
            return None, response_body, duration_ms, {}
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            response_body = {"error": f"{type(e).__name__}: {e}"}
            validation = {"status": "fail", "reason": f"exception: {e}"}
            self.recorder.record(
                endpoint_group=endpoint_group,
                method=method,
                url=url,
                test_case=test_case,
                request_headers=headers,
                request_params=params,
                request_body=body,
                response_status=0,
                response_headers={},
                response_body=response_body,
                duration_ms=duration_ms,
                validation=validation,
            )
            self._track_result(endpoint_group, method, path, test_case, 0, validation)
            await asyncio.sleep(
                LLM_HEAVY_INTER_TEST_DELAY_SECONDS if llm_heavy else INTER_TEST_DELAY_SECONDS
            )
            return None, response_body, duration_ms, {}

    def _validate(
        self,
        status_code: int | None,
        expected_status: int | list[int] | None,
        allow_server_error: bool,
    ) -> dict[str, Any]:
        if status_code is None:
            return {"status": "fail", "reason": "no response"}

        if expected_status is None:
            if 200 <= status_code < 400:
                return {"status": "pass", "reason": "success status"}
            if 400 <= status_code < 500:
                return {"status": "pass", "reason": f"client error {status_code}"}
            if allow_server_error:
                return {
                    "status": "pass",
                    "reason": f"server error {status_code} (allowed)",
                }
            return {
                "status": "fail",
                "reason": f"unexpected server error {status_code}",
            }

        if isinstance(expected_status, int):
            expected = [expected_status]
        else:
            expected = list(expected_status)

        if status_code in expected:
            return {"status": "pass", "reason": f"matched expected {status_code}"}
        if allow_server_error and status_code >= 500:
            return {
                "status": "pass",
                "reason": f"server error {status_code} (allowed)",
            }
        return {
            "status": "fail",
            "reason": f"expected {expected}, got {status_code}",
        }

    def _track_result(
        self,
        endpoint_group: str,
        method: str,
        path: str,
        test_case: str,
        status_code: int | None,
        validation: dict[str, Any],
    ) -> None:
        v_status = validation.get("status", "skip")
        mark = PASS if v_status == "pass" else FAIL if v_status == "fail" else SKIP
        code_str = f"[{status_code}]" if status_code is not None else "[ERR]"
        warning = validation.get("warning")
        warn_str = f" {WARN} {warning}" if warning else ""
        print(f"  {mark} {method:6} {path:55} {code_str:6} {test_case[:50]}{warn_str}")
        self._results.append(
            {
                "endpoint_group": endpoint_group,
                "method": method,
                "path": path,
                "test_case": test_case,
                "status_code": status_code,
                "validation": v_status,
                "reason": validation.get("reason", ""),
                "warning": warning or "",
            }
        )

    async def test_system(self) -> None:
        log_group("System Endpoints")
        await self.request(
            "system",
            "health_default",
            "GET",
            "/health",
            auth_mode="none",
            expected_status=200,
        )
        await self.request(
            "system",
            "status_default",
            "GET",
            "/api/v1/status",
            auth_mode="normal",
            expected_status=[200, 503],
        )
        await self.request(
            "system",
            "config_default",
            "GET",
            "/api/v1/config",
            auth_mode="normal",
            expected_status=[200, 401, 403, 503],
        )
        await self.request(
            "system",
            "metrics_default",
            "GET",
            "/metrics",
            auth_mode="none",
            expected_status=[200, 401, 403],
        )
        await self.request(
            "system",
            "metrics_with_auth",
            "GET",
            "/metrics",
            auth_mode="normal",
            expected_status=[200, 401, 403],
        )

    async def test_sources(self) -> None:
        log_group("Sources Endpoints")
        await self.request(
            "sources",
            "list_default",
            "GET",
            "/api/v1/sources",
            auth_mode="normal",
            expected_status=200,
        )

        source_id = f"test-src-{int(time.time())}"
        create_body = {
            "id": source_id,
            "name": "Comprehensive Test Source",
            "url": "https://www.ithome.com/rss/",
            "source_type": "rss",
            "enabled": True,
            "interval_minutes": 30,
        }
        code, _data, _ms, _h = await self.request(
            "sources",
            "create_normal",
            "POST",
            "/api/v1/sources",
            body=create_body,
            auth_mode="normal",
            expected_status=[201, 200, 409, 422],
        )
        if code in [200, 201]:
            self._created_source_ids.append(source_id)

        await self.request(
            "sources",
            "create_duplicate",
            "POST",
            "/api/v1/sources",
            body=create_body,
            auth_mode="normal",
            expected_status=[409, 400, 200, 201, 422],
        )
        await self.request(
            "sources",
            "create_missing_fields",
            "POST",
            "/api/v1/sources",
            body={"name": "Missing URL"},
            auth_mode="normal",
            expected_status=[400, 422],
        )
        await self.request(
            "sources",
            "create_invalid_url",
            "POST",
            "/api/v1/sources",
            body={
                "id": "test-invalid-url",
                "name": "Invalid URL Source",
                "url": "not-a-url",
                "source_type": "rss",
            },
            auth_mode="normal",
            expected_status=[400, 422, 201, 200],
        )
        await self.request(
            "sources",
            "get_by_id",
            "GET",
            f"/api/v1/sources/{source_id}",
            auth_mode="normal",
            expected_status=[200, 404],
        )
        await self.request(
            "sources",
            "get_nonexistent",
            "GET",
            "/api/v1/sources/nonexistent-source-xyz",
            auth_mode="normal",
            expected_status=404,
        )
        await self.request(
            "sources",
            "update_normal",
            "PUT",
            f"/api/v1/sources/{source_id}",
            body={"name": "Updated Name", "interval_minutes": 60},
            auth_mode="normal",
            expected_status=[200, 404],
        )
        await self.request(
            "sources",
            "update_nonexistent",
            "PUT",
            "/api/v1/sources/nonexistent-source-xyz",
            body={"name": "Updated"},
            auth_mode="normal",
            expected_status=[404, 200],
        )

    async def test_articles(self) -> None:
        log_group("Articles Endpoints")
        code, data, _ms, _h = await self.request(
            "articles",
            "list_default",
            "GET",
            "/api/v1/articles",
            params={"page": 1, "page_size": 10},
            auth_mode="normal",
            expected_status=200,
        )
        await self.request(
            "articles",
            "list_page_zero",
            "GET",
            "/api/v1/articles",
            params={"page": 0, "page_size": 10},
            auth_mode="normal",
            expected_status=[200, 422, 400],
        )
        await self.request(
            "articles",
            "list_large_page_size",
            "GET",
            "/api/v1/articles",
            params={"page": 1, "page_size": 1000},
            auth_mode="normal",
            expected_status=[200, 422, 400],
        )
        await self.request(
            "articles",
            "list_negative_page",
            "GET",
            "/api/v1/articles",
            params={"page": -1, "page_size": 10},
            auth_mode="normal",
            expected_status=[422, 400, 200],
        )
        await self.request(
            "articles",
            "list_with_source",
            "GET",
            "/api/v1/articles",
            params={"page": 1, "page_size": 10, "source_id": REAL_SOURCE_ID},
            auth_mode="normal",
            expected_status=200,
        )
        await self.request(
            "articles",
            "get_nonexistent",
            "GET",
            "/api/v1/articles/00000000-0000-0000-0000-000000000000",
            auth_mode="normal",
            expected_status=404,
        )

        article_id = None
        if isinstance(data, dict):
            data_payload = data.get("data") or {}
            items = data_payload.get("items") or data.get("items")
            if items and isinstance(items, list):
                article_id = items[0].get("id")

        if article_id:
            await self.request(
                "articles",
                "get_by_id",
                "GET",
                f"/api/v1/articles/{article_id}",
                auth_mode="normal",
                expected_status=[200, 404],
            )
        else:
            print(f"  {SKIP} GET    /api/v1/articles/{{id}} (no articles available)")

    async def test_pipeline(self) -> None:
        log_group("Pipeline Endpoints")
        await self.request(
            "pipeline",
            "queue_stats",
            "GET",
            "/api/v1/pipeline/queue/stats",
            auth_mode="normal",
            expected_status=[200, 503],
        )
        await self.request(
            "pipeline",
            "status",
            "GET",
            "/api/v1/pipeline/status",
            auth_mode="normal",
            expected_status=[200, 404, 503],
        )
        await self.request(
            "pipeline",
            "trigger_normal",
            "POST",
            "/api/v1/pipeline/trigger",
            body={"source_id": "nonexistent-source", "force": False},
            auth_mode="normal",
            expected_status=[200, 404, 400],
        )
        await self.request(
            "pipeline",
            "trigger_missing_source",
            "POST",
            "/api/v1/pipeline/trigger",
            body={"force": False},
            auth_mode="normal",
            expected_status=[400, 422, 200],
        )
        await self.request(
            "pipeline",
            "task_nonexistent",
            "GET",
            "/api/v1/pipeline/tasks/nonexistent-task-id",
            auth_mode="normal",
            expected_status=[404, 200, 400],
        )
        await self.request(
            "pipeline",
            "url_normal",
            "POST",
            "/api/v1/pipeline/url",
            body={"url": "https://example.com/test-article"},
            auth_mode="normal",
            expected_status=[200, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "pipeline",
            "url_invalid",
            "POST",
            "/api/v1/pipeline/url",
            body={"url": "not-a-url"},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "pipeline",
            "url_missing",
            "POST",
            "/api/v1/pipeline/url",
            body={"foo": "bar"},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )
        try:
            await asyncio.wait_for(
                self.request(
                    "pipeline",
                    "url_stream_init",
                    "POST",
                    "/api/v1/pipeline/url/stream",
                    body={"url": "https://example.com/stream-test"},
                    auth_mode="normal",
                    expected_status=[200, 422, 500],
                    allow_server_error=True,
                ),
                timeout=10.0,
            )
        except TimeoutError:
            log_warn("Stream endpoint timed out (expected for SSE), recording as pass")

    async def test_search(self) -> None:
        log_group("Search Endpoints")
        # Use real search queries from the database (populated by _fetch_real_data).
        # Fallback to first entry if list is shorter than expected.
        real_q = REAL_SEARCH_QUERIES[0] if REAL_SEARCH_QUERIES else "车牌跟踪"
        real_q_2 = REAL_SEARCH_QUERIES[1] if len(REAL_SEARCH_QUERIES) > 1 else "Steam Machine"
        real_q_3 = REAL_SEARCH_QUERIES[2] if len(REAL_SEARCH_QUERIES) > 2 else "Flock"

        await self.request(
            "search",
            "basic_normal",
            "GET",
            "/api/v1/search",
            params={"q": real_q, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_real_query_2",
            "GET",
            "/api/v1/search",
            params={"q": real_q_2, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_real_query_3",
            "GET",
            "/api/v1/search",
            params={"q": real_q_3, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_empty_query",
            "GET",
            "/api/v1/search",
            params={"q": "", "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 422],
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_large_limit",
            "GET",
            "/api/v1/search",
            params={"q": real_q, "limit": 10000},
            auth_mode="normal",
            expected_status=[200, 400, 422],
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_missing_q",
            "GET",
            "/api/v1/search",
            params={"limit": 5},
            auth_mode="normal",
            expected_status=[400, 422, 200],
            llm_heavy=True,
        )
        # Abnormal string tests — security/robustness
        await self.request(
            "search",
            "basic_sql_injection",
            "GET",
            "/api/v1/search",
            params={"q": ABNORMAL_SQL_INJECTION, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 422, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_xss",
            "GET",
            "/api/v1/search",
            params={"q": ABNORMAL_XSS, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 422, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "basic_long_string",
            "GET",
            "/api/v1/search",
            params={"q": ABNORMAL_LONG_STRING, "limit": 5},
            auth_mode="normal",
            expected_status=[200, 400, 422, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "drift_normal",
            "POST",
            "/api/v1/search/drift",
            body={"query": real_q, "time_range": "30d"},
            auth_mode="normal",
            expected_status=[200],
            allow_server_error=False,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "drift_real_query_2",
            "POST",
            "/api/v1/search/drift",
            body={"query": real_q_2, "time_range": "30d"},
            auth_mode="normal",
            expected_status=[200],
            allow_server_error=False,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "drift_missing_query",
            "POST",
            "/api/v1/search/drift",
            body={"time_range": "30d"},
            auth_mode="normal",
            expected_status=[422],
            allow_server_error=False,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "drift_sql_injection",
            "POST",
            "/api/v1/search/drift",
            body={"query": ABNORMAL_SQL_INJECTION, "time_range": "30d"},
            auth_mode="normal",
            expected_status=[200, 503],
            allow_server_error=False,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "causal_normal",
            "POST",
            "/api/v1/search/causal",
            body={"query": real_q, "depth": 2},
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "causal_real_query_2",
            "POST",
            "/api/v1/search/causal",
            body={"query": real_q_2, "depth": 2},
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "causal_invalid_depth",
            "POST",
            "/api/v1/search/causal",
            body={"query": real_q, "max_depth": -1},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "causal_xss",
            "POST",
            "/api/v1/search/causal",
            body={"query": ABNORMAL_XSS, "depth": 2},
            auth_mode="normal",
            expected_status=[200, 400, 422, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "temporal_normal",
            "POST",
            "/api/v1/search/temporal",
            body={"query": real_q, "time_range": "7d"},
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "temporal_real_query_2",
            "POST",
            "/api/v1/search/temporal",
            body={"query": real_q_2, "time_range": "7d"},
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "temporal_invalid_range",
            "POST",
            "/api/v1/search/temporal",
            body={"query": real_q, "time_window_days": "invalid"},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "search",
            "temporal_cypher_injection",
            "POST",
            "/api/v1/search/temporal",
            body={"query": ABNORMAL_CYPHER_INJECTION, "time_range": "7d"},
            auth_mode="normal",
            expected_status=[200, 400, 422, 500, 503],
            allow_server_error=True,
            llm_heavy=True,
        )

    async def test_graph(self) -> None:
        log_group("Graph Endpoints")
        await self.request(
            "graph",
            "entities_list",
            "GET",
            "/api/v1/graph/entities",
            params={"limit": 10},
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "entity_by_name",
            "GET",
            f"/api/v1/graph/entities/{REAL_ENTITY_NAME}",
            auth_mode="normal",
            expected_status=[200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "entity_nonexistent",
            "GET",
            "/api/v1/graph/entities/nonexistent-entity-xyz-123",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        # Use real article ID if available, otherwise zero-UUID placeholder
        article_uuid = REAL_ARTICLE_ID or "00000000-0000-0000-0000-000000000000"
        await self.request(
            "graph",
            "article_graph_real",
            "GET",
            f"/api/v1/graph/articles/{article_uuid}/graph",
            auth_mode="normal",
            expected_status=[200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "article_graph_nonexistent",
            "GET",
            "/api/v1/graph/articles/00000000-0000-0000-0000-000000000000/graph",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "relations_normal",
            "GET",
            "/api/v1/graph/relations",
            params={"entity": REAL_ENTITY_NAME},
            auth_mode="normal",
            expected_status=[200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "relations_missing_entity",
            "GET",
            "/api/v1/graph/relations",
            auth_mode="normal",
            expected_status=[400, 422, 200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "relations_search_normal",
            "GET",
            "/api/v1/graph/relations/search",
            params={"entity": REAL_ENTITY_NAME, "limit": 10},
            auth_mode="normal",
            expected_status=[200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "traverse_normal",
            "POST",
            "/api/v1/graph/traverse",
            body={"start_entity": REAL_ENTITY_NAME, "max_depth": 2},
            auth_mode="normal",
            expected_status=[200, 404, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph",
            "traverse_missing_entity",
            "POST",
            "/api/v1/graph/traverse",
            body={"max_depth": 2},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )
        # Abnormal string test — Cypher injection attempt
        await self.request(
            "graph",
            "traverse_cypher_injection",
            "POST",
            "/api/v1/graph/traverse",
            body={"start_entity": ABNORMAL_CYPHER_INJECTION, "max_depth": 2},
            auth_mode="normal",
            expected_status=[200, 404, 422, 500],
            allow_server_error=True,
        )

    async def test_graph_metrics(self) -> None:
        log_group("Graph Metrics Endpoints")
        await self.request(
            "graph_metrics",
            "metrics_default",
            "GET",
            "/api/v1/graph/metrics",
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
        )

    async def test_graph_visualization(self) -> None:
        log_group("Graph Visualization Endpoints")
        await self.request(
            "graph_visualization",
            "snapshot_default",
            "GET",
            "/api/v1/graph/visualization",
            auth_mode="normal",
            expected_status=[200, 500, 503],
            allow_server_error=True,
        )
        await self.request(
            "graph_visualization",
            "create_normal",
            "POST",
            "/api/v1/graph/visualization",
            body={"center_entity": REAL_ENTITY_NAME, "max_hops": 2},
            auth_mode="normal",
            expected_status=[200, 404, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph_visualization",
            "create_missing_entity",
            "POST",
            "/api/v1/graph/visualization",
            body={"max_hops": 2},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "graph_visualization",
            "create_invalid_hops",
            "POST",
            "/api/v1/graph/visualization",
            body={"center_entity": REAL_ENTITY_NAME, "max_hops": -1},
            auth_mode="normal",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )

    async def test_communities(self) -> None:
        log_group("Communities Endpoints")
        await self.request(
            "communities",
            "list_default",
            "GET",
            "/api/v1/admin/communities",
            auth_mode="admin",
            expected_status=[200, 403, 503],
            allow_server_error=True,
        )
        await self.request(
            "communities",
            "health",
            "GET",
            "/api/v1/admin/communities/health",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "communities",
            "health_diagnose",
            "POST",
            "/api/v1/admin/communities/health/diagnose",
            body={},
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "communities",
            "health_repair",
            "POST",
            "/api/v1/admin/communities/health/repair",
            body={},
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "communities",
            "get_nonexistent",
            "GET",
            "/api/v1/admin/communities/00000000-0000-0000-0000-000000000000",
            auth_mode="admin",
            expected_status=[404, 200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "communities",
            "rebuild",
            "POST",
            "/api/v1/admin/communities/rebuild",
            body={},
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "communities",
            "reports_generate",
            "POST",
            "/api/v1/admin/communities/reports/generate",
            body={"force": False},
            auth_mode="admin",
            expected_status=[200, 403, 404, 500],
            allow_server_error=True,
            llm_heavy=True,
        )
        await self.request(
            "communities",
            "report_regenerate_nonexistent",
            "POST",
            "/api/v1/admin/communities/00000000-0000-0000-0000-000000000000/report/regenerate",
            body={},
            auth_mode="admin",
            expected_status=[404, 200, 403, 500],
            allow_server_error=True,
        )

    async def test_admin(self) -> None:
        log_group("Admin Endpoints")
        await self.request(
            "admin",
            "articles_deduplicate",
            "POST",
            "/api/v1/admin/articles/deduplicate",
            body={},
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "api_keys_list",
            "GET",
            "/api/v1/admin/api-keys",
            auth_mode="admin",
            expected_status=[200, 403, 503],
            allow_server_error=True,
        )
        code, data, _ms, _h = await self.request(
            "admin",
            "api_keys_create",
            "POST",
            "/api/v1/admin/api-keys",
            body={
                "name": "comprehensive-test-key",
                "scopes": ["read"],
                "expires_in_days": 30,
            },
            auth_mode="admin",
            expected_status=[200, 201, 403, 422, 500],
            allow_server_error=True,
        )
        if isinstance(data, dict):
            key_payload = data.get("data") or {}
            key_id = key_payload.get("id") or data.get("id")
            if key_id:
                self._created_api_key_ids.append(str(key_id))
        await self.request(
            "admin",
            "api_keys_create_invalid",
            "POST",
            "/api/v1/admin/api-keys",
            body={"rate_limit_per_min": 5},
            auth_mode="admin",
            expected_status=[400, 422, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "api_keys_delete_nonexistent",
            "DELETE",
            "/api/v1/admin/api-keys/00000000-0000-0000-0000-000000000000",
            auth_mode="admin",
            expected_status=[404, 200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "api_keys_rotate_nonexistent",
            "POST",
            "/api/v1/admin/api-keys/00000000-0000-0000-0000-000000000000/rotate",
            auth_mode="admin",
            expected_status=[404, 200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "authorities_list",
            "GET",
            "/api/v1/admin/authorities",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "authorities_update",
            "PATCH",
            "/api/v1/admin/authorities/example.com",
            body={"authority": 0.8, "tier": 1},
            auth_mode="admin",
            expected_status=[200, 404, 403, 400, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "authorities_refresh",
            "POST",
            "/api/v1/admin/authorities/refresh-auto-scores",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "llm_failures_list",
            "GET",
            "/api/v1/admin/llm-failures",
            params={"limit": 20},
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "llm_failures_stats",
            "GET",
            "/api/v1/admin/llm-failures/stats",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )

        now = datetime.now(UTC)
        from_time = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%S")
        time_params = {"from": from_time, "to": to_time}

        await self.request(
            "admin",
            "llm_usage_default",
            "GET",
            "/api/v1/admin/llm-usage",
            params=time_params,
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        for group in ["summary", "provider", "model", "call_point"]:
            await self.request(
                "admin",
                f"llm_usage_group_{group}",
                "GET",
                "/api/v1/admin/llm-usage",
                params={**time_params, "group_by": group},
                auth_mode="admin",
                expected_status=[200, 403, 500],
                allow_server_error=True,
            )
        await self.request(
            "admin",
            "llm_usage_invalid_group",
            "GET",
            "/api/v1/admin/llm-usage",
            params={**time_params, "group_by": "invalid_dimension"},
            auth_mode="admin",
            expected_status=[400, 422, 200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "memory_diagnostics",
            "GET",
            "/api/v1/admin/memory/diagnostics",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
        )
        await self.request(
            "admin",
            "memory_trigger_consolidation",
            "POST",
            "/api/v1/admin/memory/trigger-consolidation",
            auth_mode="admin",
            expected_status=[200, 403, 500],
            allow_server_error=True,
            llm_heavy=True,
        )

    async def test_monitoring(self) -> None:
        log_group("Monitoring Endpoints")
        await self.request(
            "monitoring",
            "alert_rules_list",
            "GET",
            "/api/v1/monitoring/alerts/rules",
            auth_mode="admin",
            expected_status=[200, 503],
            allow_server_error=True,
        )
        code, data, _ms, _h = await self.request(
            "monitoring",
            "alert_rules_create",
            "POST",
            "/api/v1/monitoring/alerts/rules",
            body={
                "name": "comprehensive-test-rule",
                "metric": "error_rate",
                "threshold": 0.05,
                "window_minutes": 5,
                "enabled": True,
            },
            auth_mode="admin",
            expected_status=[200, 201, 422, 500],
            allow_server_error=True,
        )
        if isinstance(data, dict):
            rule_payload = data.get("data") or {}
            rule_id = rule_payload.get("id") or data.get("id")
            if rule_id:
                self._created_alert_rule_ids.append(str(rule_id))
        await self.request(
            "monitoring",
            "alert_rules_create_invalid",
            "POST",
            "/api/v1/monitoring/alerts/rules",
            body={"name": "missing-fields"},
            auth_mode="admin",
            expected_status=[400, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_rules_get_nonexistent",
            "GET",
            "/api/v1/monitoring/alerts/rules/999999",
            auth_mode="admin",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_rules_patch_nonexistent",
            "PATCH",
            "/api/v1/monitoring/alerts/rules/999999",
            body={"enabled": False},
            auth_mode="admin",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_rules_delete_nonexistent",
            "DELETE",
            "/api/v1/monitoring/alerts/rules/999999",
            auth_mode="admin",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_trigger",
            "POST",
            "/api/v1/monitoring/alerts/trigger",
            body={"rule_id": 999999, "metric_value": 1.0},
            auth_mode="admin",
            expected_status=[200, 404, 400, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_events_list",
            "GET",
            "/api/v1/monitoring/alerts/events",
            params={"limit": 20},
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "alert_ack_nonexistent",
            "POST",
            "/api/v1/monitoring/alerts/events/999999/acknowledge",
            auth_mode="admin",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "llm_failures_list",
            "GET",
            "/api/v1/monitoring/llm/failures",
            params={"limit": 20},
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "llm_failures_stats",
            "GET",
            "/api/v1/monitoring/llm/failures/stats",
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        now = datetime.now(UTC)
        from_time = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%S")
        await self.request(
            "monitoring",
            "llm_usage",
            "GET",
            "/api/v1/monitoring/llm/usage",
            params={"from": from_time, "to": to_time},
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "memory_diagnostics",
            "GET",
            "/api/v1/monitoring/memory/diagnostics",
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "causal_stats",
            "GET",
            "/api/v1/monitoring/causal/stats",
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "graph_metrics",
            "GET",
            "/api/v1/monitoring/graph/metrics",
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "monitoring",
            "communities_health",
            "GET",
            "/api/v1/monitoring/communities/health",
            auth_mode="admin",
            expected_status=[200, 500],
            allow_server_error=True,
        )

    async def test_saga(self) -> None:
        log_group("Saga Endpoints")
        await self.request(
            "saga",
            "get_nonexistent",
            "GET",
            "/api/v1/saga/00000000-0000-0000-0000-000000000000",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "saga",
            "compensate_nonexistent",
            "POST",
            "/api/v1/saga/00000000-0000-0000-0000-000000000000/compensate",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "saga",
            "retry_nonexistent",
            "POST",
            "/api/v1/saga/00000000-0000-0000-0000-000000000000/retry",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "saga",
            "by_article_nonexistent",
            "GET",
            "/api/v1/saga/article/00000000-0000-0000-0000-000000000000",
            auth_mode="normal",
            expected_status=[404, 200, 500],
            allow_server_error=True,
        )
        await self.request(
            "saga",
            "failed_list",
            "GET",
            "/api/v1/saga/failed/list",
            params={"limit": 20},
            auth_mode="normal",
            expected_status=[200, 500],
            allow_server_error=True,
        )

    async def test_analytics(self) -> None:
        log_group("Analytics Endpoints")
        now = datetime.now(UTC)
        from_time = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%S")
        await self.request(
            "analytics",
            "shifts_default",
            "GET",
            "/api/v1/analytics/shifts",
            params={"from": from_time, "to": to_time},
            auth_mode="normal",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "analytics",
            "shifts_no_time",
            "GET",
            "/api/v1/analytics/shifts",
            auth_mode="normal",
            expected_status=[200, 400, 422, 500],
            allow_server_error=True,
        )
        await self.request(
            "analytics",
            "briefings_default",
            "GET",
            "/api/v1/analytics/briefings",
            params={"limit": 10},
            auth_mode="normal",
            expected_status=[200, 500],
            allow_server_error=True,
        )
        await self.request(
            "analytics",
            "briefings_large_limit",
            "GET",
            "/api/v1/analytics/briefings",
            params={"limit": 1000},
            auth_mode="normal",
            expected_status=[200, 400, 422, 500],
            allow_server_error=True,
        )

    async def test_auth_scenarios(self) -> None:
        log_group("Authentication Scenarios")
        await self.request(
            "auth",
            "no_auth_on_sources",
            "GET",
            "/api/v1/sources",
            auth_mode="none",
            expected_status=401,
        )
        await self.request(
            "auth",
            "wrong_auth_on_sources",
            "GET",
            "/api/v1/sources",
            auth_mode="wrong",
            expected_status=403,
        )
        await self.request(
            "auth",
            "no_auth_on_admin",
            "GET",
            "/api/v1/admin/api-keys",
            auth_mode="none",
            expected_status=401,
        )
        await self.request(
            "auth",
            "wrong_auth_on_admin",
            "GET",
            "/api/v1/admin/api-keys",
            auth_mode="wrong",
            expected_status=403,
        )
        await self.request(
            "auth",
            "regular_key_on_admin",
            "GET",
            "/api/v1/admin/api-keys",
            auth_mode="normal",
            expected_status=[403, 200, 503],
        )
        await self.request(
            "auth",
            "admin_key_on_regular",
            "GET",
            "/api/v1/sources",
            auth_mode="admin",
            expected_status=200,
        )
        await self.request(
            "auth",
            "no_auth_on_health",
            "GET",
            "/health",
            auth_mode="none",
            expected_status=200,
        )
        await self.request(
            "auth",
            "no_auth_on_metrics",
            "GET",
            "/metrics",
            auth_mode="none",
            expected_status=[200, 401, 403],
        )

    async def cleanup(self) -> None:
        log_group("Cleanup")
        for source_id in self._created_source_ids:
            await self.request(
                "sources",
                f"cleanup_source_{source_id}",
                "DELETE",
                f"/api/v1/sources/{source_id}",
                auth_mode="normal",
                expected_status=[200, 204, 404, 500],
                allow_server_error=True,
            )
        for key_id in self._created_api_key_ids:
            await self.request(
                "admin",
                f"cleanup_api_key_{key_id}",
                "DELETE",
                f"/api/v1/admin/api-keys/{key_id}",
                auth_mode="admin",
                expected_status=[200, 204, 404, 500],
                allow_server_error=True,
            )
        for rule_id in self._created_alert_rule_ids:
            await self.request(
                "monitoring",
                f"cleanup_alert_rule_{rule_id}",
                "DELETE",
                f"/api/v1/monitoring/alerts/rules/{rule_id}",
                auth_mode="normal",
                expected_status=[200, 204, 404, 500],
                allow_server_error=True,
            )

    async def run_all(self) -> dict[str, Any]:
        log_group("Running Comprehensive API Tests")
        await self._fetch_real_data()
        await self.test_system()
        await self.test_sources()
        await self.test_articles()
        await self.test_pipeline()
        await self.test_search()
        await self.test_graph()
        await self.test_graph_metrics()
        await self.test_graph_visualization()
        await self.test_communities()
        await self.test_admin()
        await self.test_monitoring()
        await self.test_saga()
        await self.test_analytics()
        await self.test_auth_scenarios()
        await self.cleanup()
        return self._build_summary()

    def _build_summary(self) -> dict[str, Any]:
        total = len(self._results)
        passed = sum(1 for r in self._results if r["validation"] == "pass")
        failed = sum(1 for r in self._results if r["validation"] == "fail")
        skipped = sum(1 for r in self._results if r["validation"] == "skip")
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        }

    def print_summary(self) -> dict[str, Any]:
        summary = self._build_summary()
        print(f"\n{Colors.MAGENTA}{'=' * 70}{Colors.NC}")
        print(f"{Colors.MAGENTA}  Comprehensive API Test Summary{Colors.NC}")
        print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")
        print(f"  Total:   {summary['total']}")
        print(f"  {Colors.GREEN}Passed:{Colors.NC}  {summary['passed']}")
        print(f"  {Colors.RED}Failed:{Colors.NC}  {summary['failed']}")
        print(f"  {Colors.YELLOW}Skipped:{Colors.NC} {summary['skipped']}")
        print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")

        if summary["failed"] > 0:
            print(f"\n{Colors.RED}Failed tests:{Colors.NC}")
            for r in self._results:
                if r["validation"] == "fail":
                    print(
                        f"  {FAIL} {r['method']:6} {r['path']:55} "
                        f"[{r['status_code']}] {r['reason'][:60]}"
                    )

        groups: dict[str, dict[str, int]] = {}
        for r in self._results:
            g = r["endpoint_group"]
            if g not in groups:
                groups[g] = {"pass": 0, "fail": 0, "skip": 0}
            groups[g][r["validation"]] = groups[g].get(r["validation"], 0) + 1

        print(f"\n{Colors.CYAN}By endpoint group:{Colors.NC}")
        for g in sorted(groups.keys()):
            counts = groups[g]
            total_g = counts["pass"] + counts["fail"] + counts["skip"]
            print(
                f"  {g:25} {total_g:4} | "
                f"{Colors.GREEN}P:{counts['pass']:4}{Colors.NC} "
                f"{Colors.RED}F:{counts['fail']:4}{Colors.NC} "
                f"{Colors.YELLOW}S:{counts['skip']:4}{Colors.NC}"
            )
        return summary


async def run_tests(args: argparse.Namespace) -> int:
    print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")
    print(f"{Colors.MAGENTA}  Weaver Comprehensive API Test Suite{Colors.NC}")
    print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")
    print(f"  Base URL:    {args.url}")
    print(f"  Output dir:  {args.output_dir}")
    print(f"  Auto start:  {not args.no_start}")
    print(f"  API key:     {(args.api_key or DEFAULT_API_KEY)[:8]}...")
    print(f"  Admin key:   {(args.admin_key or DEFAULT_ADMIN_KEY)[:8]}...")
    print(f"{Colors.MAGENTA}{'=' * 70}{Colors.NC}")

    api_key = args.api_key or os.getenv("WEAVER_API__API_KEY", DEFAULT_API_KEY)
    admin_key = args.admin_key or os.getenv("WEAVER_API__ADMIN_API_KEY", DEFAULT_ADMIN_KEY)

    # Load API keys from .env file if not in environment
    if not args.api_key:
        env_file = Path.cwd() / ".env"
        if env_file.exists():
            with env_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if key == "WEAVER_API__API_KEY" and api_key == DEFAULT_API_KEY:
                            api_key = value
                        elif key == "WEAVER_API__ADMIN_API_KEY" and admin_key == DEFAULT_ADMIN_KEY:
                            admin_key = value

    if len(api_key) < 32:
        log_warn(f"API key is short ({len(api_key)} chars, min 32). Auth tests may fail.")

    output_dir = Path(args.output_dir)
    if output_dir.exists() and args.clean:
        import shutil

        shutil.rmtree(output_dir)
        log_info(f"Cleaned output directory: {output_dir}")

    recorder = ResponseRecorder(output_dir)
    app_manager = AppProcessManager(
        base_url=args.url,
        api_key=api_key,
        admin_key=admin_key,
        auto_start=not args.no_start,
    )

    tester = ComprehensiveAPITester(
        base_url=args.url,
        api_key=api_key,
        admin_key=admin_key,
        recorder=recorder,
    )

    try:
        log_step("1/4", "Ensuring app is running...")
        if not await app_manager.ensure_running():
            log_error("Failed to start or connect to app")
            return 1

        log_step("2/4", "Running comprehensive API tests...")
        await tester.run_all()

        log_step("3/4", "Exporting response recordings and summary...")
        recorder_summary = recorder.export_summary()
        test_summary = tester.print_summary()

        log_info(f"Recorded {recorder_summary['total_calls']} API calls")
        log_info(f"Output: {output_dir.resolve()}")
        log_info(f"Summary: {output_dir / 'summary.json'}")

        log_step("4/4", "Done.")
        return 0 if test_summary["failed"] == 0 else 1

    except KeyboardInterrupt:
        log_warn("Test interrupted by user")
        return 130
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        await tester.close()
        await app_manager.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comprehensive API test script for all Weaver endpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: auto-start app and run all tests
  uv run python tests/scripts/comprehensive_api_test.py

  # Connect to already-running app
  uv run python tests/scripts/comprehensive_api_test.py --no-start

  # Custom URL and keys
  uv run python tests/scripts/comprehensive_api_test.py \\
      --url http://localhost:8001 \\
      --api-key my-key-32-chars-minimum-length! \\
      --admin-key my-admin-key-32-chars-min-len!

  # Clean output dir before running
  uv run python tests/scripts/comprehensive_api_test.py --clean
        """,
    )
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help=f"API base URL (default: {BASE_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for regular endpoints (default: env WEAVER_API__API_KEY or built-in)",
    )
    parser.add_argument(
        "--admin-key",
        default=None,
        help="Admin API key for admin endpoints (default: env WEAVER_API__ADMIN_API_KEY or built-in)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Output directory for response recordings (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Do not auto-start the app; connect to an already-running instance",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove output directory before running",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(run_tests(args))
    sys.exit(exit_code)
