# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for PortAnnouncer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.net.port_announcer import PortAnnouncer


class TestPortAnnouncer:
    """Tests for PortAnnouncer."""

    def test_announce_logs_port_check_when_unchanged(self, tmp_path: Path) -> None:
        """Should log port_check when port is unchanged from original."""
        env_file = tmp_path / ".env.weaver"
        announcer = PortAnnouncer(env_file=env_file)

        with patch("core.net.port_announcer.log") as mock_log:
            announcer.announce("127.0.0.1", 8000, 8000)

            mock_log.info.assert_called_once_with(
                "port_check", host="127.0.0.1", port=8000, status="available"
            )

        # Should not write env file when port unchanged
        assert not env_file.exists()

    def test_announce_logs_port_resolved_when_changed(self, tmp_path: Path) -> None:
        """Should log port_resolved when port differs from original."""
        env_file = tmp_path / ".env.weaver"
        announcer = PortAnnouncer(env_file=env_file)

        with patch("core.net.port_announcer.log") as mock_log:
            announcer.announce("127.0.0.1", 8005, 8000)

            mock_log.info.assert_called_once_with(
                "port_resolved",
                host="127.0.0.1",
                original_port=8000,
                actual_port=8005,
            )

    def test_announce_writes_env_file(self, tmp_path: Path) -> None:
        """Should write WEAVER_ACTUAL_PORT to env file."""
        env_file = tmp_path / ".env.weaver"
        announcer = PortAnnouncer(env_file=env_file)

        with patch("core.net.port_announcer.log"):
            announcer.announce("127.0.0.1", 8005, 8000)

        assert env_file.exists()
        content = env_file.read_text()
        assert "WEAVER_ACTUAL_PORT=8005" in content

    def test_announce_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories for env file if needed."""
        env_file = tmp_path / "subdir" / ".env.weaver"
        announcer = PortAnnouncer(env_file=env_file)

        with patch("core.net.port_announcer.log"):
            announcer.announce("127.0.0.1", 8005, 8000)

        assert env_file.exists()
        assert env_file.parent.is_dir()

    def test_announce_handles_file_write_failure(self, tmp_path: Path) -> None:
        """Should log warning and continue when file write fails."""
        # Create a file and make it read-only (parent dir still writable)
        env_file = tmp_path / ".env.weaver"
        env_file.write_text("existing content")
        import os

        os.chmod(env_file, 0o444)  # Read-only

        announcer = PortAnnouncer(env_file=env_file)

        with patch("core.net.port_announcer.log") as mock_log:
            # Should not raise, just log warning
            announcer.announce("127.0.0.1", 8005, 8000)

            # Check that warning was logged
            warning_calls = [
                call
                for call in mock_log.warning.call_args_list
                if "port_announce_file_failed" in str(call)
            ]
            assert len(warning_calls) == 1

        # Cleanup - restore write permission
        os.chmod(env_file, 0o644)

    def test_announce_updates_prometheus_metric(self, tmp_path: Path) -> None:
        """Should update weaver_server_port Prometheus metric."""
        env_file = tmp_path / ".env.weaver"
        announcer = PortAnnouncer(env_file=env_file)

        mock_metrics = MagicMock()

        with (
            patch("core.net.port_announcer.log"),
            patch("core.net.port_announcer.PortAnnouncer._update_metric") as mock_update,
        ):
            announcer.announce("127.0.0.1", 8005, 8000)

            # Verify metric update was called
            mock_update.assert_called_once_with("127.0.0.1", 8005)

    def test_announce_uses_default_env_file_path(self) -> None:
        """Should use .env.weaver in cwd by default."""
        announcer = PortAnnouncer()
        assert announcer._env_file.name == ".env.weaver"
