# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for PortFinder."""

from __future__ import annotations

import socket

import pytest

from core.net import PortFinder
from core.net.errors import PortExhaustionError


class TestIsPortAvailable:
    """Tests for PortFinder.is_port_available()."""

    @staticmethod
    def _grab_free_port() -> tuple[int, socket.socket]:
        """Ask the OS for an ephemeral port and return (port, bound_socket).

        The caller MUST close the returned socket when done. Used to avoid
        hardcoding ports that may collide with long-running system
        processes (e.g. an IDE's outgoing connection on 54322).
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1], s

    def test_returns_true_when_port_is_free(self) -> None:
        """Port should be reported as available when nothing is bound to it."""
        port, s = self._grab_free_port()
        try:
            s.close()  # release immediately, port is now free
            assert PortFinder.is_port_available("127.0.0.1", port) is True
        finally:
            # socket already closed above; guard double-close with try/except
            try:
                s.close()
            except OSError:
                pass

    def test_returns_false_when_port_is_in_use(self) -> None:
        """Port should be reported as unavailable when already bound."""
        # Use OS-allocated ephemeral port to avoid collisions with
        # long-running system processes on hardcoded ports.
        port, s = self._grab_free_port()
        try:
            assert PortFinder.is_port_available("127.0.0.1", port) is False
        finally:
            s.close()

    def test_returns_true_after_socket_closed(self) -> None:
        """Port should become available after socket is closed."""
        port, s = self._grab_free_port()
        s.close()
        # Socket is now closed, port should be available
        assert PortFinder.is_port_available("127.0.0.1", port) is True


class TestFindAvailablePort:
    """Tests for PortFinder.find_available_port()."""

    def test_returns_original_port_when_available(self) -> None:
        """Should return the starting port if it's available."""
        port = PortFinder.find_available_port("127.0.0.1", 54324, 100)
        assert port == 54324

    def test_finds_available_port_when_start_blocked(self) -> None:
        """Should find an available port when the starting port is unavailable."""
        # Bind and listen to fully occupy the port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 54325))
            s.listen(1)

            # Should find an available port (not 54325)
            port = PortFinder.find_available_port("127.0.0.1", 54325, 10)
            assert port != 54325
            assert 1024 <= port <= 65535

    def test_searches_bidirectional_order(self) -> None:
        """Should search bidirectionally: start, +1, -1, +2, -2..."""
        # Bind and listen on multiple consecutive ports to verify search order
        # Block 54326 and 54327, but leave 54325 available
        sockets: list[socket.socket] = []
        try:
            # Block ports 54326 and 54327
            for port in [54326, 54327]:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", port))
                s.listen(1)
                sockets.append(s)

            # Start at 54326, blocked
            # Search order: 54326 (blocked), 54327 (blocked), 54325 (available!)
            port = PortFinder.find_available_port("127.0.0.1", 54326, 10)
            assert port == 54325

        finally:
            for s in sockets:
                s.close()

    def test_raises_on_exhaustion(self) -> None:
        """Should raise PortExhaustionError when max_attempts is exceeded."""
        # Create sockets to exhaust a specific search range
        sockets: list[socket.socket] = []
        try:
            # Block enough ports to exhaust the search
            # Bidirectional search tries: start, start+1, start-1, start+2, start-2...
            # So we need to block enough to hit max_attempts
            for i in range(10):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.bind(("127.0.0.1", 54330 + i))
                    s.listen(1)
                    sockets.append(s)
                except OSError:
                    s.close()

            # Also block the ports in the opposite direction
            for i in range(1, 6):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.bind(("127.0.0.1", 54330 - i))
                    s.listen(1)
                    sockets.append(s)
                except OSError:
                    s.close()

            with pytest.raises(PortExhaustionError) as exc_info:
                PortFinder.find_available_port("127.0.0.1", 54330, max_attempts=5)

            assert exc_info.value.host == "127.0.0.1"
            assert exc_info.value.start_port == 54330
            assert exc_info.value.attempts == 5

        finally:
            for s in sockets:
                s.close()

    def test_skips_privileged_ports(self) -> None:
        """Should skip ports below 1024 when searching."""
        # Bind and listen on port 1024
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 1024))
            s.listen(1)

            # Should skip 1023 and find 1025 (or higher)
            port = PortFinder.find_available_port("127.0.0.1", 1024, 100)
            assert port >= 1025

    def test_respects_max_port_limit(self) -> None:
        """Should not try ports above 65535."""
        # Start near the limit
        port = PortFinder.find_available_port("127.0.0.1", 65530, 10)
        assert port <= 65535
