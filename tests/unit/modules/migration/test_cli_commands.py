# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.cli.commands module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from modules.migration.cli.commands import app

runner = CliRunner()


class TestMigrateRelationalCommand:
    """Test migrate relational command."""

    def test_relational_invalid_source(self):
        """Test with invalid source database."""
        result = runner.invoke(
            app,
            ["relational", "--from", "invalid", "--to", "duckdb"],
        )

        assert result.exit_code == 1
        assert "Invalid source" in result.output

    def test_relational_invalid_target(self):
        """Test with invalid target database."""
        result = runner.invoke(
            app,
            ["relational", "--from", "postgres", "--to", "invalid"],
        )

        assert result.exit_code == 1
        assert "Invalid target" in result.output

    def test_relational_same_source_target(self):
        """Test with same source and target."""
        result = runner.invoke(
            app,
            ["relational", "--from", "postgres", "--to", "postgres"],
        )

        assert result.exit_code == 1
        assert "must be different" in result.output

    def test_relational_dry_run(self):
        """Test dry run mode."""
        result = runner.invoke(
            app,
            ["relational", "--from", "postgres", "--to", "duckdb", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "postgres" in result.output
        assert "duckdb" in result.output

    def test_relational_dry_run_with_tables(self):
        """Test dry run with specific tables."""
        result = runner.invoke(
            app,
            [
                "relational",
                "--from",
                "postgres",
                "--to",
                "duckdb",
                "--table",
                "users",
                "--table",
                "articles",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "users" in result.output
        assert "articles" in result.output

    def test_relational_dry_run_with_incremental(self):
        """Test dry run with incremental options."""
        result = runner.invoke(
            app,
            [
                "relational",
                "--from",
                "postgres",
                "--to",
                "duckdb",
                "--incremental",
                "updated_at",
                "--since",
                "2024-01-01",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "incremental" in result.output.lower()


class TestMigrateGraphCommand:
    """Test migrate graph command."""

    def test_graph_invalid_source(self):
        """Test with invalid source database."""
        result = runner.invoke(
            app,
            ["graph", "--from", "invalid", "--to", "ladybug"],
        )

        assert result.exit_code == 1
        assert "Invalid source" in result.output

    def test_graph_invalid_target(self):
        """Test with invalid target database."""
        result = runner.invoke(
            app,
            ["graph", "--from", "neo4j", "--to", "invalid"],
        )

        assert result.exit_code == 1
        assert "Invalid target" in result.output

    def test_graph_same_source_target(self):
        """Test with same source and target."""
        result = runner.invoke(
            app,
            ["graph", "--from", "neo4j", "--to", "neo4j"],
        )

        assert result.exit_code == 1
        assert "must be different" in result.output

    def test_graph_dry_run(self):
        """Test dry run mode."""
        result = runner.invoke(
            app,
            ["graph", "--from", "neo4j", "--to", "ladybug", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "neo4j" in result.output
        assert "ladybug" in result.output

    def test_graph_dry_run_with_nodes_and_rels(self):
        """Test dry run with nodes and relations."""
        result = runner.invoke(
            app,
            [
                "graph",
                "--from",
                "neo4j",
                "--to",
                "ladybug",
                "--node",
                "Entity",
                "--rel",
                "RELATED_TO",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        # Check output contains node info
        assert "DRY RUN" in result.output


class TestListMappingsCommand:
    """Test list-mappings command."""

    def test_list_mappings_no_directory(self):
        """Test with non-existent directory."""
        result = runner.invoke(
            app,
            ["list-mappings", "--dir", "/nonexistent"],
        )

        assert "not found" in result.output.lower()

    def test_list_mappings_empty_directory(self, tmp_path):
        """Test with empty directory."""
        result = runner.invoke(
            app,
            ["list-mappings", "--dir", str(tmp_path)],
        )

        assert "No mapping files" in result.output

    def test_list_mappings_with_files(self, tmp_path):
        """Test with mapping files."""
        # Create some YAML files
        (tmp_path / "mapping1.yaml").write_text("nodes: []")
        (tmp_path / "mapping2.yml").write_text("nodes: []")

        result = runner.invoke(
            app,
            ["list-mappings", "--dir", str(tmp_path)],
        )

        assert "mapping1.yaml" in result.output
        assert "mapping2.yml" in result.output


class TestCLIIntegration:
    """Integration tests for CLI commands."""

    def test_help_shows_commands(self):
        """Test help shows all commands."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "relational" in result.output
        assert "graph" in result.output
        assert "list-mappings" in result.output

    def test_relational_help(self):
        """Test relational command help."""
        result = runner.invoke(app, ["relational", "--help"])

        assert result.exit_code == 0
        assert "postgres" in result.output
        assert "duckdb" in result.output

    def test_graph_help(self):
        """Test graph command help."""
        result = runner.invoke(app, ["graph", "--help"])

        assert result.exit_code == 0
        assert "neo4j" in result.output
        assert "ladybug" in result.output
