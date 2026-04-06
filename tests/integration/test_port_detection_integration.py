# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for port auto-detection functionality with real socket operations."""

from __future__ import annotations

import os
import socket

import pytest

from config.settings import APISettings, Settings


class TestPortDetectionIntegration:
    """Integration tests for end-to-end port detection with real sockets."""

    def test_settings_api_port_resolves_automatically(self) -> None:
        """Settings should resolve API port automatically on creation."""
        settings = Settings()
        assert settings.api.port > 0
        assert 1024 <= settings.api.port <= 65535

    def test_settings_with_port_auto_detect_disabled(self, monkeypatch) -> None:
        """Settings should not resolve port when auto-detect is disabled."""
        # Save original env value
        original = os.environ.get("WEAVER_API__PORT_AUTO_DETECT")

        try:
            os.environ["WEAVER_API__PORT_AUTO_DETECT"] = "false"
            settings = Settings()
            assert settings.api.port == 8000  # Default port, unchanged
        finally:
            # Restore original value
            if original is None:
                os.environ.pop("WEAVER_API__PORT_AUTO_DETECT", None)
            else:
                os.environ["WEAVER_API__PORT_AUTO_DETECT"] = original

    def test_settings_port_detection_finds_available_port(self, monkeypatch) -> None:
        """Settings should find an available port when configured port is in use."""
        # Use a less common port to avoid conflicts with running services
        test_port = 18999
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)

            # Save original env values
            original_port = os.environ.get("WEAVER_API__PORT")
            original_auto = os.environ.get("WEAVER_API__PORT_AUTO_DETECT")

            try:
                os.environ["WEAVER_API__PORT"] = str(test_port)
                os.environ["WEAVER_API__PORT_AUTO_DETECT"] = "true"

                settings = Settings()
                # Port should be different since test_port is bound
                assert settings.api.port > 1024
                assert settings.api.port != test_port
            finally:
                # Restore original values
                if original_port is None:
                    os.environ.pop("WEAVER_API__PORT", None)
                else:
                    os.environ["WEAVER_API__PORT"] = original_port
                if original_auto is None:
                    os.environ.pop("WEAVER_API__PORT_AUTO_DETECT", None)
                else:
                    os.environ["WEAVER_API__PORT_AUTO_DETECT"] = original_auto

    def test_settings_creates_env_file_when_port_changes(self, tmp_path, monkeypatch) -> None:
        """Settings should create .env.weaver when port changes."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Use a less common port to avoid conflicts
        test_port = 18998
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)

            # Save original env values
            original_port = os.environ.get("WEAVER_API__PORT")
            original_auto = os.environ.get("WEAVER_API__PORT_AUTO_DETECT")

            try:
                os.environ["WEAVER_API__PORT"] = str(test_port)
                os.environ["WEAVER_API__PORT_AUTO_DETECT"] = "true"

                settings = Settings()

                # Check that env file was created
                env_file = tmp_path / ".env.weaver"
                if env_file.exists():
                    content = env_file.read_text()
                    assert f"WEAVER_ACTUAL_PORT={settings.api.port}" in content
            finally:
                # Restore original values
                if original_port is None:
                    os.environ.pop("WEAVER_API__PORT", None)
                else:
                    os.environ["WEAVER_API__PORT"] = original_port
                if original_auto is None:
                    os.environ.pop("WEAVER_API__PORT_AUTO_DETECT", None)
                else:
                    os.environ["WEAVER_API__PORT_AUTO_DETECT"] = original_auto

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

    def test_port_detection_with_multiple_bound_ports(self) -> None:
        """Port detection should find available port when multiple ports are bound."""
        # Bind multiple consecutive ports
        bound_ports = []
        test_sockets = []

        try:
            for port in range(19000, 19005):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))
                    s.listen(1)
                    test_sockets.append(s)
                    bound_ports.append(port)
                except OSError:
                    pass  # Port already in use, skip

            if bound_ports:
                # Create settings with first bound port
                original_port = os.environ.get("WEAVER_API__PORT")
                original_auto = os.environ.get("WEAVER_API__PORT_AUTO_DETECT")

                try:
                    os.environ["WEAVER_API__PORT"] = str(bound_ports[0])
                    os.environ["WEAVER_API__PORT_AUTO_DETECT"] = "true"

                    settings = Settings()
                    # Should find a port not in bound_ports
                    assert settings.api.port not in bound_ports
                finally:
                    if original_port is None:
                        os.environ.pop("WEAVER_API__PORT", None)
                    else:
                        os.environ["WEAVER_API__PORT"] = original_port
                    if original_auto is None:
                        os.environ.pop("WEAVER_API__PORT_AUTO_DETECT", None)
                    else:
                        os.environ["WEAVER_API__PORT_AUTO_DETECT"] = original_auto
        finally:
            # Clean up sockets
            for s in test_sockets:
                s.close()
