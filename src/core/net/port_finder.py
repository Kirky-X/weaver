# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Port availability detection utilities."""

from __future__ import annotations

import socket

from core.net.errors import PortExhaustionError


class PortFinder:
    """Utility class for finding available network ports."""

    @staticmethod
    def is_port_available(host: str, port: int) -> bool:
        """Check if a port is available for binding.

        Args:
            host: The host address to check.
            port: The port number to check.

        Returns:
            True if the port is available, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                # Don't use SO_REUSEADDR - we want to detect if port is truly available
                sock.bind((host, port))
                return True
        except OSError:
            return False

    @staticmethod
    def find_available_port(
        host: str,
        start_port: int,
        max_attempts: int = 100,
    ) -> int:
        """Find an available port using bidirectional search.

        Search order: start_port → +1 → -1 → +2 → -2 → ...
        Skips privileged ports (<1024) and ports above 65535.

        Args:
            host: The host address to search.
            start_port: The starting port for the search.
            max_attempts: Maximum number of ports to try.

        Returns:
            The first available port number.

        Raises:
            PortExhaustionError: If no available port is found within max_attempts.
        """
        visited: set[int] = set()

        for i in range(max_attempts):
            # Bidirectional search: prioritize upward
            if i % 2 == 0:
                port = start_port + (i // 2)
            else:
                port = start_port - ((i + 1) // 2)

            # Skip privileged ports and out-of-range ports
            if port < 1024 or port > 65535:
                continue

            # Skip already visited ports
            if port in visited:
                continue
            visited.add(port)

            if PortFinder.is_port_available(host, port):
                return port

        raise PortExhaustionError(host, start_port, max_attempts)
