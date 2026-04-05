# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Port announcement utilities."""

from __future__ import annotations

from pathlib import Path

from core.observability.logging import get_logger

log = get_logger("port_announcer")


class PortAnnouncer:
    """Utility class for announcing the actual port being used."""

    def __init__(self, env_file: Path | None = None) -> None:
        """Initialize the port announcer.

        Args:
            env_file: Path to the env file for port persistence.
                      Defaults to .env.weaver in current working directory.
        """
        self._env_file = env_file or Path.cwd() / ".env.weaver"

    def announce(self, host: str, port: int, original_port: int) -> None:
        """Announce the actual port being used.

        Logs to console, writes to env file, and updates Prometheus metrics.

        Args:
            host: The host address.
            port: The actual port being used.
            original_port: The originally configured port.
        """
        if port == original_port:
            # Port unchanged - simple log
            log.info("port_check", host=host, port=port, status="available")
        else:
            # Port changed - full announcement
            log.info(
                "port_resolved",
                host=host,
                original_port=original_port,
                actual_port=port,
            )

            # Write to env file
            self._write_env_file(port)

            # Update Prometheus metric
            self._update_metric(host, port)

    def _write_env_file(self, port: int) -> None:
        """Write the actual port to the env file.

        Args:
            port: The actual port to write.
        """
        try:
            self._env_file.parent.mkdir(parents=True, exist_ok=True)
            self._env_file.write_text(f"WEAVER_ACTUAL_PORT={port}\n")
            log.debug("port_env_file_written", path=str(self._env_file), port=port)
        except Exception as e:
            log.warning(
                "port_announce_file_failed",
                path=str(self._env_file),
                error=str(e),
            )

    def _update_metric(self, host: str, port: int) -> None:
        """Update the Prometheus server_port metric.

        Args:
            host: The host address.
            port: The actual port.
        """
        try:
            from core.observability.metrics import metrics

            if hasattr(metrics, "server_port"):
                metrics.server_port.labels(host=host).set(port)
        except ImportError:
            # Metrics module not available, skip silently
            pass
        except Exception as e:
            log.warning("port_metric_update_failed", error=str(e))
