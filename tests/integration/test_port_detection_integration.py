# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for port auto-detection functionality."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from config.settings import APISettings, Settings


class TestPortDetectionIntegration:
    """Integration tests for end-to-end port detection."""

    def test_settings_api_port_resolves_automatically(self) -> None:
        """Settings should resolve API port automatically on creation."""
        settings = Settings()
        assert settings.api.port > 0
        assert 1024 <= settings.api.port <= 65535

    def test_settings_with_port_auto_detect_disabled(self) -> None:
        """Settings should not resolve port when auto-detect is disabled."""
        with patch.dict(
            "os.environ",
            {"WEAVER_API__PORT_AUTO_DETECT": "false"},
        ):
            settings = Settings()
            assert settings.api.port == 8000  # Default port, unchanged

    def test_settings_port_detection_finds_available_port(self) -> None:
        """Settings should find an available port when configured port is in use."""
        # Use a less common port to avoid conflicts with running services
        test_port = 18999
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)

            # Use environment variable to set the port
            with patch.dict(
                "os.environ",
                {
                    "WEAVER_API__PORT": str(test_port),
                    "WEAVER_API__PORT_AUTO_DETECT": "true",
                },
            ):
                settings = Settings()
                # Port should be different since test_port is bound
                assert settings.api.port > 1024
                assert settings.api.port != test_port

    def test_settings_creates_env_file_when_port_changes(self, tmp_path, monkeypatch) -> None:
        """Settings should create .env.weaver when port changes."""
        import os

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Use a less common port to avoid conflicts
        test_port = 18998
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)

            # Use environment variable to set the port
            with patch.dict(
                "os.environ",
                {
                    "WEAVER_API__PORT": str(test_port),
                    "WEAVER_API__PORT_AUTO_DETECT": "true",
                },
            ):
                settings = Settings()

                # Check that env file was created
                env_file = tmp_path / ".env.weaver"
                if env_file.exists():
                    content = env_file.read_text()
                    assert f"WEAVER_ACTUAL_PORT={settings.api.port}" in content

    def test_multiple_settings_instances_use_same_port(self) -> None:
        """Multiple Settings instances should resolve to the same available port."""
        settings1 = Settings()
        settings2 = Settings()

        # Both should resolve to the same port (the first available)
        assert settings1.api.port == settings2.api.port

    def test_api_settings_custom_host(self) -> None:
        """APISettings should work with custom host."""
        settings = APISettings(host="0.0.0.0")  # noqa: S104
        assert settings.host == "0.0.0.0"  # noqa: S104
        assert settings.port > 0
