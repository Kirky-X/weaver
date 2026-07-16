# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""API response recorder for comprehensive endpoint testing.

Records all HTTP requests and responses to JSON files for later analysis
and cross-validation with source data.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class APIResponseRecorder:
    """Records API requests and responses to JSON files.

    Each call is saved as a separate JSON file containing:
    - Request details (URL, method, headers, params, body)
    - Response details (status code, headers, body, duration)
    - Metadata (timestamp, test case name, endpoint category)
    """

    def __init__(self, output_dir: str | Path = "temp/api_responses"):
        """Initialize the recorder.

        Args:
            output_dir: Directory to save response records.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        endpoint: str,
        method: str,
        url: str,
        request_headers: dict[str, str] | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: Any = None,
        response_status: int = 0,
        response_headers: dict[str, str] | None = None,
        response_body: Any = None,
        duration_ms: float = 0.0,
        test_case: str = "manual",
        validation_result: dict[str, Any] | None = None,
    ) -> Path:
        """Record a single API call.

        Args:
            endpoint: Endpoint category (e.g., "sources", "articles").
            method: HTTP method (GET, POST, etc.).
            url: Full request URL.
            request_headers: Request headers.
            request_params: Query parameters.
            request_body: Request body (JSON-serializable).
            response_status: HTTP status code.
            response_headers: Response headers.
            response_body: Response body (JSON-serializable).
            duration_ms: Request duration in milliseconds.
            test_case: Test case name or description.
            validation_result: Optional data validation result.

        Returns:
            Path to the saved JSON file.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "metadata": {
                "timestamp": timestamp,
                "endpoint": endpoint,
                "test_case": test_case,
                "duration_ms": round(duration_ms, 2),
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

        if validation_result:
            record["validation"] = validation_result

        self.records.append(record)

        # Save to file
        endpoint_dir = self.output_dir / endpoint
        endpoint_dir.mkdir(parents=True, exist_ok=True)

        # Create safe filename from test_case
        safe_name = self._safe_filename(test_case)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{safe_name}_{ts}.json"
        filepath = endpoint_dir / filename

        filepath.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))

        return filepath

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all recorded calls.

        Returns:
            Summary dict with counts and statistics.
        """
        by_endpoint: dict[str, int] = {}
        by_status: dict[str, int] = {}
        total_duration = 0.0

        for record in self.records:
            endpoint = record["metadata"]["endpoint"]
            status = str(record["response"]["status_code"])
            duration = record["metadata"]["duration_ms"]

            by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            total_duration += duration

        return {
            "total_calls": len(self.records),
            "by_endpoint": by_endpoint,
            "by_status": by_status,
            "total_duration_ms": round(total_duration, 2),
            "avg_duration_ms": round(total_duration / max(len(self.records), 1), 2),
        }

    def export_summary(self, filepath: str | Path | None = None) -> dict[str, Any]:
        """Export summary to JSON file.

        Args:
            filepath: Optional file path. Defaults to temp/api_responses/summary.json.

        Returns:
            Summary dict.
        """
        summary = self.get_summary()

        if filepath is None:
            filepath = self.output_dir / "summary.json"
        else:
            filepath = Path(filepath)

        filepath.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary

    def _sanitize_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Sanitize headers by masking sensitive values.

        Args:
            headers: Original headers dict.

        Returns:
            Sanitized headers dict.
        """
        sensitive_keys = {"authorization", "x-api-key", "cookie", "x-csrf-token"}
        sanitized = {}
        for key, value in headers.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = value[:8] + "..." if len(value) > 8 else "***"
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Convert a string to a safe filename.

        Args:
            name: Original name.

        Returns:
            Safe filename string.
        """
        # Replace unsafe characters
        safe = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        safe = "".join(c for c in safe if c.isalnum() or c in "_-")
        # Truncate if too long
        return safe[:100] if len(safe) > 100 else safe
