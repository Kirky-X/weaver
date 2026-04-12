# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Data validator for cross-referencing API responses with source data.

Validates API responses against the original data in:
- data/weaver.duckdb (DuckDB database)
- data/ladybug.db (Ladybug graph database)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DataValidator:
    """Validates API responses against source data.

    Reads from DuckDB and Ladybug databases to verify API responses
    contain accurate and complete data.
    """

    def __init__(self, data_dir: str | Path = "data"):
        """Initialize the validator.

        Args:
            data_dir: Path to the data directory containing database files.
        """
        self.data_dir = Path(data_dir)
        self.duckdb_path = self.data_dir / "weaver.duckdb"
        self.ladybug_path = self.data_dir / "ladybug.db"
        self.validation_results: list[dict[str, Any]] = []

    def validate_sources_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Validate sources API response against DuckDB data.

        Args:
            response_data: API response body.

        Returns:
            Validation result dict.
        """
        result = {"valid": True, "checks": [], "errors": []}

        try:
            import duckdb

            if not self.duckdb_path.exists():
                result["valid"] = False
                result["errors"].append(f"DuckDB file not found: {self.duckdb_path}")
                return result

            conn = duckdb.connect(database=str(self.duckdb_path))

            # Check sources table exists
            tables = conn.execute("SHOW TABLES").fetchdf()
            if "sources" not in tables["name"].values:
                result["valid"] = False
                result["errors"].append("sources table not found in DuckDB")
                return result

            # Get expected source count
            expected_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

            # Validate response
            if "data" in response_data:
                sources = response_data["data"]
                if isinstance(sources, list):
                    actual_count = len(sources)
                    result["checks"].append(
                        {
                            "check": "source_count",
                            "expected": expected_count,
                            "actual": actual_count,
                            "passed": actual_count == expected_count,
                        }
                    )
                    if actual_count != expected_count:
                        result["valid"] = False
                        result["errors"].append(
                            f"Source count mismatch: expected {expected_count}, got {actual_count}"
                        )

            conn.close()
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {e!s}")

        self.validation_results.append({"type": "sources", "result": result})
        return result

    def validate_articles_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Validate articles API response against DuckDB data.

        Args:
            response_data: API response body.

        Returns:
            Validation result dict.
        """
        result = {"valid": True, "checks": [], "errors": []}

        try:
            import duckdb

            if not self.duckdb_path.exists():
                result["valid"] = False
                result["errors"].append(f"DuckDB file not found: {self.duckdb_path}")
                return result

            conn = duckdb.connect(database=str(self.duckdb_path))

            # Get expected article count
            expected_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

            # Validate response
            if "data" in response_data:
                data = response_data["data"]

                # Check if paginated response
                if isinstance(data, dict) and "items" in data:
                    actual_count = len(data["items"])
                    result["checks"].append(
                        {
                            "check": "articles_in_page",
                            "actual": actual_count,
                            "passed": actual_count <= expected_count,
                        }
                    )
                elif isinstance(data, list):
                    actual_count = len(data)
                    result["checks"].append(
                        {
                            "check": "article_count",
                            "expected": expected_count,
                            "actual": actual_count,
                            "passed": actual_count == expected_count,
                        }
                    )

            conn.close()
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {e!s}")

        self.validation_results.append({"type": "articles", "result": result})
        return result

    def validate_single_article(
        self, article_id: str, response_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate a single article response against DuckDB data.

        Args:
            article_id: Article UUID.
            response_data: API response body.

        Returns:
            Validation result dict.
        """
        result = {"valid": True, "checks": [], "errors": []}

        try:
            import duckdb

            if not self.duckdb_path.exists():
                result["valid"] = False
                result["errors"].append(f"DuckDB file not found: {self.duckdb_path}")
                return result

            conn = duckdb.connect(database=str(self.duckdb_path))

            # Query article from DuckDB
            row = conn.execute("SELECT * FROM articles WHERE id = ?", [article_id]).fetchone()

            if row is None:
                result["valid"] = False
                result["errors"].append(f"Article not found in DuckDB: {article_id}")
                return result

            # Get column names
            columns = [desc[0] for desc in conn.description]
            expected_article = dict(zip(columns, row, strict=False))

            # Validate response fields
            if "data" in response_data:
                api_article = response_data["data"]

                # Check critical fields match
                critical_fields = ["id", "title", "category", "language"]
                for field in critical_fields:
                    if field in expected_article and field in api_article:
                        matches = expected_article[field] == api_article[field]
                        result["checks"].append(
                            {
                                "check": f"field_{field}",
                                "expected": expected_article[field],
                                "actual": api_article[field],
                                "passed": matches,
                            }
                        )
                        if not matches:
                            result["valid"] = False
                            result["errors"].append(
                                f"Field '{field}' mismatch: expected {expected_article[field]}, got {api_article[field]}"
                            )

            conn.close()
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {e!s}")

        self.validation_results.append({"type": "article_detail", "result": result})
        return result

    def validate_relations_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Validate graph relations response against Ladybug data.

        Args:
            response_data: API response body.

        Returns:
            Validation result dict.
        """
        result = {"valid": True, "checks": [], "errors": []}

        try:
            import sqlite3

            if not self.ladybug_path.exists():
                result["valid"] = False
                result["errors"].append(f"Ladybug file not found: {self.ladybug_path}")
                return result

            conn = sqlite3.connect(str(self.ladybug_path))

            # Get expected relation types count
            cursor = conn.execute("SELECT COUNT(*) FROM relation_types")
            expected_count = cursor.fetchone()[0]

            # Validate response
            if "data" in response_data:
                relations = response_data["data"]
                if isinstance(relations, list):
                    actual_count = len(relations)
                    result["checks"].append(
                        {
                            "check": "relation_type_count",
                            "expected": expected_count,
                            "actual": actual_count,
                            "passed": actual_count == expected_count,
                        }
                    )
                    if actual_count != expected_count:
                        result["valid"] = False
                        result["errors"].append(
                            f"Relation count mismatch: expected {expected_count}, got {actual_count}"
                        )

            conn.close()
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {e!s}")

        self.validation_results.append({"type": "relations", "result": result})
        return result

    def generate_report(self, output_path: str | Path | None = None) -> str:
        """Generate validation report.

        Args:
            output_path: Optional file path for the report.

        Returns:
            Report content as string.
        """
        lines = [
            "# API 数据验证报告",
            "",
            f"**总验证次数**: {len(self.validation_results)}",
            "",
        ]

        passed = sum(1 for v in self.validation_results if v["result"]["valid"])
        failed = len(self.validation_results) - passed
        lines.append(f"**通过**: {passed}")
        lines.append(f"**失败**: {failed}")
        lines.append("")

        for validation in self.validation_results:
            vtype = validation["type"]
            vresult = validation["result"]
            status = "✓ 通过" if vresult["valid"] else "✗ 失败"

            lines.append(f"## {vtype} - {status}")
            lines.append("")

            if vresult["checks"]:
                lines.append("### 检查项")
                lines.append("")
                for check in vresult["checks"]:
                    icon = "✓" if check["passed"] else "✗"
                    lines.append(f"- {icon} {check['check']}: {check}")
                lines.append("")

            if vresult["errors"]:
                lines.append("### 错误")
                lines.append("")
                for error in vresult["errors"]:
                    lines.append(f"- {error}")
                lines.append("")

        report = "\n".join(lines)

        if output_path:
            Path(output_path).write_text(report, encoding="utf-8")

        return report
