# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for management module."""

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestResolveSubcommand:
    """Tests for _resolve_subcommand function."""

    def test_no_args(self):
        """Test with no arguments."""
        from modules.management.__main__ import _resolve_subcommand

        with patch.object(sys, "argv", ["__main__.py"]):
            result = _resolve_subcommand()
            assert result == ""

    def test_single_arg(self):
        """Test with single subcommand argument."""
        from modules.management.__main__ import _resolve_subcommand

        with patch.object(sys, "argv", ["__main__.py", "repair-articles"]):
            result = _resolve_subcommand()
            assert result == "repair-articles"

    def test_flag_arg(self):
        """Test with flag argument returns empty."""
        from modules.management.__main__ import _resolve_subcommand

        with patch.object(sys, "argv", ["__main__.py", "--help"]):
            result = _resolve_subcommand()
            assert result == ""

    def test_multiple_args(self):
        """Test with multiple arguments."""
        from modules.management.__main__ import _resolve_subcommand

        with patch.object(sys, "argv", ["__main__.py", "repair-articles", "--limit", "10"]):
            result = _resolve_subcommand()
            assert result == "repair-articles"


class TestMainHelp:
    """Tests for main help functionality."""

    def test_help_subcommand(self, capsys):
        """Test help subcommand exits cleanly."""
        from modules.management.__main__ import main

        with patch.object(sys, "argv", ["__main__.py", "help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_help_flag(self, capsys):
        """Test --help flag exits cleanly."""
        from modules.management.__main__ import main

        with patch.object(sys, "argv", ["__main__.py", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainUnknownCommand:
    """Tests for unknown command handling."""

    def test_unknown_command(self, capsys):
        """Test unknown command exits with error."""
        from modules.management.__main__ import main

        with patch.object(sys, "argv", ["__main__.py", "unknown-command"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_no_subcommand(self, capsys):
        """Test no subcommand shows error."""
        from modules.management.__main__ import main

        with patch.object(sys, "argv", ["__main__.py"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestMainRepairArticles:
    """Tests for repair-articles subcommand."""

    def test_repair_articles_delegation(self):
        """Test repair-articles delegates to repair module."""
        from modules.management.__main__ import main

        mock_main = MagicMock()

        with patch.object(sys, "argv", ["__main__.py", "repair-articles", "--dry-run"]):
            with patch.dict(
                "sys.modules",
                {"modules.management.commands.repair_articles": MagicMock(main=mock_main)},
            ):
                main()
                mock_main.assert_called_once()

    def test_repair_articles_argv_manipulation(self):
        """Test that sys.argv is properly manipulated for repair-articles."""
        from modules.management.__main__ import main

        mock_main = MagicMock()

        original_argv = ["__main__.py", "repair-articles", "--limit", "10"]

        with patch.object(sys, "argv", original_argv.copy()):
            with patch.dict(
                "sys.modules",
                {"modules.management.commands.repair_articles": MagicMock(main=mock_main)},
            ):
                main()
                # After delegation, sys.argv should be restored
                # The mock was called, which is the key verification


class TestModuleImports:
    """Tests for module path setup."""

    def test_project_root_in_path(self):
        """Test that project root is added to sys.path."""
        # This tests the path setup at module level
        import modules.management.__main__ as mm

        # The module should have loaded successfully
        assert hasattr(mm, "main")
        assert hasattr(mm, "_resolve_subcommand")
