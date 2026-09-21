# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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

        Note:
            There is an inherent TOCTOU race between the availability check
            and the caller's actual bind: another process can grab the port
            in between. Callers that need a guaranteed exclusive port should
            retry on ``Address already in use`` at bind time.

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
        probed = 0
        i = 0
        # Only in-range, unvisited probes count against max_attempts:
        # skipping an out-of-range candidate must not consume the budget,
        # otherwise a start_port near a boundary (e.g. 1024 searching
        # downward) exhausts the loop without ever probing max_attempts
        # ports. The extra cap guards against pathological inputs.
        max_iterations = 4 * max_attempts + 1024

        while probed < max_attempts and i < max_iterations:
            i += 1
            # Bidirectional search: prioritize upward
            if (i - 1) % 2 == 0:
                port = start_port + ((i - 1) // 2)
            else:
                port = start_port - (i // 2)

            # Skip privileged ports and out-of-range ports (free of charge)
            if port < 1024 or port > 65535:
                continue

            # Skip already visited ports (free of charge)
            if port in visited:
                continue
            visited.add(port)
            probed += 1

            if PortFinder.is_port_available(host, port):
                return port

        raise PortExhaustionError(host, start_port, probed)
