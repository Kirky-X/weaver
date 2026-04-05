# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Port-related exceptions."""

from __future__ import annotations


class PortError(Exception):
    """Base exception for port-related errors."""

    pass


class PortExhaustionError(PortError):
    """Raised when no available port can be found within the search range.

    Attributes:
        host: The host address that was searched.
        start_port: The starting port for the search.
        attempts: Number of ports attempted.
    """

    def __init__(self, host: str, start_port: int, attempts: int) -> None:
        self.host = host
        self.start_port = start_port
        self.attempts = attempts
        super().__init__(
            f"No available port found for {host} "
            f"after {attempts} attempts starting from {start_port}"
        )
