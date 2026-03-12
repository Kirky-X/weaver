"""Interleaver: round-robin sort items by host to spread load."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from core.observability.logging import get_logger

log = get_logger("interleaver")


class Interleaver:
    """Interleaves items by host for balanced crawling.

    Sorts items in round-robin order across different hosts
    to prevent hammering a single site.
    """

    @staticmethod
    def interleave(items: list) -> list:
        """Interleave items by source host.

        Args:
            items: List of items with `.url` attribute.

        Returns:
            Items sorted in round-robin by host.
        """
        if not items:
            return []

        # Group by host
        host_groups: dict[str, list] = defaultdict(list)
        for item in items:
            host = urlparse(item.url).netloc
            host_groups[host].append(item)

        # Round-robin merge
        result: list = []
        hosts = list(host_groups.keys())
        max_len = max(len(group) for group in host_groups.values())

        for i in range(max_len):
            for host in hosts:
                group = host_groups[host]
                if i < len(group):
                    result.append(group[i])

        log.debug(
            "interleaved",
            total=len(result),
            hosts=len(hosts),
        )
        return result
