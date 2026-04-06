# Copyright (c) 2026 KirkyX. All Rights Reserved
"""PhishTank data synchronization and URL lookup.

PhishTank is a free community-driven phishing URL database.
This module provides:
- Periodic data download from PhishTank
- Local caching and indexing
- Fast URL lookup

Data source: https://data.phishtank.com/data/online-valid.json
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.observability.logging import get_logger
from core.security.models import CheckResult, CheckSource, URLRisk

log = get_logger("security.phishtank")


@dataclass
class PhishTankEntry:
    """PhishTank phishing URL record."""

    url: str
    """The phishing URL."""

    phish_id: str
    """Unique PhishTank ID."""

    submission_time: datetime
    """When the URL was submitted."""

    verified: bool
    """Whether the entry has been verified."""

    online: bool
    """Whether the phishing site is still online."""

    target: str = ""
    """The targeted brand or organization."""


class PhishTankSync:
    """PhishTank data synchronization and lookup.

    Downloads PhishTank data periodically and maintains local indexes
    for fast URL lookup.

    Attributes:
        DATA_URL: PhishTank data download URL.
        _fetcher: HttpxFetcher for downloading data.
        _data_path: Local storage path.
        _sync_interval: Time between syncs.
        _enabled: Whether sync is enabled.
        _url_index: URL to entry mapping.
        _domain_index: Domain to URL set mapping.
        _last_sync: Last sync timestamp.
    """

    DATA_URL = "https://data.phishtank.com/data/online-valid.json"

    def __init__(
        self,
        fetcher: Any,
        data_path: str = "data/phishtank.json",
        sync_interval_hours: int = 6,
        enabled: bool = True,
    ) -> None:
        """Initialize PhishTank sync.

        Args:
            fetcher: HttpxFetcher instance.
            data_path: Local storage path for PhishTank data.
            sync_interval_hours: Hours between syncs.
            enabled: Whether sync is enabled.
        """
        self._fetcher = fetcher
        self._data_path = Path(data_path)
        self._sync_interval = timedelta(hours=sync_interval_hours)
        self._enabled = enabled

        self._url_index: dict[str, PhishTankEntry] = {}
        self._domain_index: dict[str, set[str]] = {}
        self._last_sync: datetime | None = None

    async def initialize(self) -> None:
        """Initialize: load local data or trigger first sync."""
        if not self._enabled:
            return

        if self._data_path.exists():
            await self._load_local_data()
            log.info("phishtank_loaded", entries=len(self._url_index))
        else:
            await self.sync()

    async def sync(self) -> None:
        """Download latest data from PhishTank."""
        if not self._enabled:
            return

        try:
            log.info("phishtank_sync_start")
            status_code, response_text, _ = await self._fetcher.fetch(self.DATA_URL)

            if status_code != 200:
                log.warning("phishtank_sync_failed", status=status_code)
                return

            data = json.loads(response_text)
            await self._process_data(data)
            await self._save_local_data(data)

            self._last_sync = datetime.now()
            log.info("phishtank_sync_complete", entries=len(self._url_index))

        except Exception as e:
            log.warning("phishtank_sync_error", error=str(e))

    async def _process_data(self, data: list[dict[str, Any]]) -> None:
        """Process PhishTank data and build indexes.

        Args:
            data: List of PhishTank entry dictionaries.
        """
        self._url_index.clear()
        self._domain_index.clear()

        for entry in data:
            try:
                url = entry.get("url", "")
                if not url:
                    continue

                phish_entry = PhishTankEntry(
                    url=url,
                    phish_id=str(entry.get("phish_id", "")),
                    submission_time=self._parse_time(entry.get("submission_time", "")),
                    verified=entry.get("verified", "no") == "yes",
                    online=entry.get("online", "no") == "yes",
                    target=entry.get("target", ""),
                )

                # URL index
                self._url_index[url] = phish_entry

                # Domain index
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                if domain not in self._domain_index:
                    self._domain_index[domain] = set()
                self._domain_index[domain].add(url)

            except Exception as e:
                log.debug("phishtank_entry_skip", error=str(e))
                continue

    def _parse_time(self, time_str: str) -> datetime:
        """Parse PhishTank timestamp.

        Args:
            time_str: Timestamp string.

        Returns:
            Parsed datetime.
        """
        try:
            # PhishTank format: "2024-01-15T10:30:00+00:00" or similar
            if " " in time_str:
                time_str = time_str.replace(" ", "T")
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except Exception:
            return datetime.now()

    async def _save_local_data(self, data: list[dict[str, Any]]) -> None:
        """Save data to local file.

        Args:
            data: PhishTank data to save.
        """
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._data_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "updated_at": datetime.now().isoformat(),
                    "entries": data,
                },
                f,
            )

    async def _load_local_data(self) -> None:
        """Load data from local file."""
        try:
            with open(self._data_path, encoding="utf-8") as f:
                stored = json.load(f)
            await self._process_data(stored.get("entries", []))
        except Exception as e:
            log.warning("phishtank_load_error", error=str(e))

    def check(self, url: str) -> CheckResult:
        """Check URL against PhishTank database.

        Args:
            url: URL to check.

        Returns:
            CheckResult with the check result.
        """
        if not self._enabled:
            return CheckResult(
                source=CheckSource.PHISHTANK,
                risk=URLRisk.SAFE,
                message="PhishTank disabled",
            )

        # Exact URL match
        if url in self._url_index:
            entry = self._url_index[url]
            return CheckResult(
                source=CheckSource.PHISHTANK,
                risk=URLRisk.BLOCKED,
                message=f"Found in PhishTank database (ID: {entry.phish_id})",
                details={
                    "phish_id": entry.phish_id,
                    "target": entry.target,
                    "verified": entry.verified,
                },
            )

        # Domain match
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if domain in self._domain_index:
            return CheckResult(
                source=CheckSource.PHISHTANK,
                risk=URLRisk.HIGH,
                message="Domain has known phishing URLs",
                details={
                    "domain": domain,
                    "phishing_urls": len(self._domain_index[domain]),
                },
            )

        return CheckResult(
            source=CheckSource.PHISHTANK,
            risk=URLRisk.SAFE,
            message="Not found in PhishTank database",
        )

    def needs_sync(self) -> bool:
        """Check if sync is needed.

        Returns:
            True if sync interval has elapsed.
        """
        if not self._last_sync:
            return True
        return datetime.now() - self._last_sync > self._sync_interval

    @property
    def entry_count(self) -> int:
        """Get number of cached entries.

        Returns:
            Number of phishing URLs in cache.
        """
        return len(self._url_index)
