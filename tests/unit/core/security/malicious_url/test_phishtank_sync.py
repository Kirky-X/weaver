# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for PhishTankSync."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.security.malicious_url.phishtank_sync import PhishTankEntry, PhishTankSync
from core.security.models import CheckSource, URLRisk

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PHISHTANK_DATA = [
    {
        "url": "https://evil-login.com/bank/signin",
        "phish_id": 12345,
        "submission_time": "2026-01-15T10:30:00+00:00",
        "verified": "yes",
        "online": "yes",
        "target": "Bank of Example",
    },
    {
        "url": "https://phish-site.com/paypal/login",
        "phish_id": 67890,
        "submission_time": "2026-02-20T14:00:00+00:00",
        "verified": "no",
        "online": "yes",
        "target": "PayPal",
    },
]


@pytest.fixture
def mock_fetcher():
    """Create a mock fetcher that returns PhishTank data."""
    fetcher = AsyncMock()
    fetcher.fetch = AsyncMock(return_value=(200, json.dumps(SAMPLE_PHISHTANK_DATA), {}))
    return fetcher


@pytest.fixture
def phishtank(mock_fetcher, tmp_path):
    """Create a PhishTankSync instance with temp storage."""
    data_path = str(tmp_path / "phishtank.json")
    return PhishTankSync(
        fetcher=mock_fetcher,
        data_path=data_path,
        sync_interval_hours=6,
        enabled=True,
    )


@pytest.fixture
def disabled_phishtank(mock_fetcher, tmp_path):
    """Create a disabled PhishTankSync instance."""
    data_path = str(tmp_path / "phishtank.json")
    return PhishTankSync(
        fetcher=mock_fetcher,
        data_path=data_path,
        enabled=False,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestPhishTankInit:
    """Tests for PhishTankSync initialization."""

    def test_default_state(self, phishtank):
        assert phishtank._enabled is True
        assert phishtank.entry_count == 0
        assert phishtank._last_sync is None
        assert phishtank.needs_sync() is True

    def test_disabled_state(self, disabled_phishtank):
        assert disabled_phishtank._enabled is False

    async def test_initialize_triggers_sync_when_no_local_data(self, phishtank, mock_fetcher):
        await phishtank.initialize()
        assert phishtank.entry_count == 2
        mock_fetcher.fetch.assert_called_once()

    async def test_initialize_disabled_no_sync(self, disabled_phishtank, mock_fetcher):
        await disabled_phishtank.initialize()
        mock_fetcher.fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class TestPhishTankSync:
    """Tests for PhishTankSync data sync."""

    async def test_sync_downloads_and_processes(self, phishtank, mock_fetcher):
        await phishtank.sync()
        assert phishtank.entry_count == 2
        assert phishtank._last_sync is not None

    async def test_sync_saves_local_file(self, phishtank, tmp_path):
        await phishtank.sync()
        data_file = tmp_path / "phishtank.json"
        assert data_file.exists()
        stored = json.loads(data_file.read_text())
        assert "entries" in stored
        assert len(stored["entries"]) == 2

    async def test_sync_handles_http_error(self, phishtank, mock_fetcher):
        mock_fetcher.fetch.return_value = (500, "Internal Server Error", {})
        await phishtank.sync()
        assert phishtank.entry_count == 0

    async def test_sync_handles_exception(self, phishtank, mock_fetcher):
        mock_fetcher.fetch.side_effect = ConnectionError("network down")
        await phishtank.sync()
        assert phishtank.entry_count == 0

    async def test_sync_disabled_is_noop(self, disabled_phishtank, mock_fetcher):
        await disabled_phishtank.sync()
        mock_fetcher.fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Data Processing
# ---------------------------------------------------------------------------


class TestPhishTankDataProcessing:
    """Tests for PhishTankSync data processing."""

    async def test_process_data_builds_url_index(self, phishtank):
        await phishtank._process_data(SAMPLE_PHISHTANK_DATA)
        assert "https://evil-login.com/bank/signin" in phishtank._url_index
        assert "https://phish-site.com/paypal/login" in phishtank._url_index

    async def test_process_data_builds_domain_index(self, phishtank):
        await phishtank._process_data(SAMPLE_PHISHTANK_DATA)
        assert "evil-login.com" in phishtank._domain_index
        assert "phish-site.com" in phishtank._domain_index

    async def test_process_data_skips_empty_urls(self, phishtank):
        data = [{"url": "", "phish_id": 1}, {"url": "https://ok.com", "phish_id": 2}]
        await phishtank._process_data(data)
        assert phishtank.entry_count == 1

    async def test_process_data_clears_previous(self, phishtank):
        await phishtank._process_data(SAMPLE_PHISHTANK_DATA)
        assert phishtank.entry_count == 2
        await phishtank._process_data([SAMPLE_PHISHTANK_DATA[0]])
        assert phishtank.entry_count == 1

    async def test_process_data_handles_bad_entry(self, phishtank):
        data = [{"url": "https://ok.com", "phish_id": 1}, {"url": None}]
        await phishtank._process_data(data)
        assert phishtank.entry_count == 1


# ---------------------------------------------------------------------------
# Check / Lookup
# ---------------------------------------------------------------------------


class TestPhishTankCheck:
    """Tests for PhishTankSync URL lookup."""

    async def _load_data(self, phishtank):
        await phishtank._process_data(SAMPLE_PHISHTANK_DATA)

    async def test_check_exact_match_returns_blocked(self, phishtank):
        await self._load_data(phishtank)
        result = phishtank.check("https://evil-login.com/bank/signin")
        assert result.source == CheckSource.PHISHTANK
        assert result.risk == URLRisk.BLOCKED
        assert "12345" in result.message
        assert result.details["phish_id"] == "12345"
        assert result.details["target"] == "Bank of Example"

    async def test_check_domain_match_returns_high(self, phishtank):
        await self._load_data(phishtank)
        result = phishtank.check("https://evil-login.com/other/page")
        assert result.risk == URLRisk.HIGH
        assert result.details["domain"] == "evil-login.com"

    async def test_check_safe_url(self, phishtank):
        await self._load_data(phishtank)
        result = phishtank.check("https://google.com/search?q=test")
        assert result.risk == URLRisk.SAFE

    async def test_check_disabled_returns_safe(self, disabled_phishtank):
        result = disabled_phishtank.check("https://evil-login.com/bank/signin")
        assert result.risk == URLRisk.SAFE
        assert "disabled" in result.message.lower()

    async def test_check_empty_index(self, phishtank):
        result = phishtank.check("https://example.com")
        assert result.risk == URLRisk.SAFE


# ---------------------------------------------------------------------------
# Needs Sync
# ---------------------------------------------------------------------------


class TestPhishTankNeedsSync:
    """Tests for PhishTankSync.needs_sync()."""

    def test_needs_sync_no_last_sync(self, phishtank):
        assert phishtank.needs_sync() is True

    def test_needs_sync_recently_synced(self, phishtank):
        phishtank._last_sync = datetime.now()
        assert phishtank.needs_sync() is False

    def test_needs_sync_expired(self, phishtank):
        phishtank._last_sync = datetime.now() - timedelta(hours=7)
        assert phishtank.needs_sync() is True

    def test_needs_sync_exactly_at_interval(self, phishtank):
        phishtank._last_sync = datetime.now() - timedelta(hours=6, minutes=1)
        assert phishtank.needs_sync() is True


# ---------------------------------------------------------------------------
# Time Parsing
# ---------------------------------------------------------------------------


class TestPhishTankTimeParsing:
    """Tests for PhishTankSync._parse_time()."""

    def test_parse_iso_format(self, phishtank):
        dt = phishtank._parse_time("2026-01-15T10:30:00+00:00")
        assert isinstance(dt, datetime)
        assert dt.year == 2026

    def test_parse_space_separated(self, phishtank):
        dt = phishtank._parse_time("2026-01-15 10:30:00+00:00")
        assert isinstance(dt, datetime)

    def test_parse_z_suffix(self, phishtank):
        dt = phishtank._parse_time("2026-01-15T10:30:00Z")
        assert isinstance(dt, datetime)

    def test_parse_invalid_returns_now(self, phishtank):
        dt = phishtank._parse_time("not-a-date")
        assert isinstance(dt, datetime)

    def test_parse_empty_returns_now(self, phishtank):
        dt = phishtank._parse_time("")
        assert isinstance(dt, datetime)


# ---------------------------------------------------------------------------
# Local File Persistence
# ---------------------------------------------------------------------------


class TestPhishTankLocalData:
    """Tests for PhishTankSync local file persistence."""

    async def test_save_and_load(self, phishtank, tmp_path):
        await phishtank._save_local_data(SAMPLE_PHISHTANK_DATA)
        assert (tmp_path / "phishtank.json").exists()

        phishtank2 = PhishTankSync(
            fetcher=AsyncMock(),
            data_path=str(tmp_path / "phishtank.json"),
            enabled=True,
        )
        await phishtank2._load_local_data()
        assert phishtank2.entry_count == 2

    async def test_load_handles_corrupt_file(self, phishtank, tmp_path):
        (tmp_path / "phishtank.json").write_text("not valid json{{{")

        phishtank2 = PhishTankSync(
            fetcher=AsyncMock(),
            data_path=str(tmp_path / "phishtank.json"),
            enabled=True,
        )
        await phishtank2._load_local_data()
        assert phishtank2.entry_count == 0

    async def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "phishtank.json"
        pt = PhishTankSync(fetcher=AsyncMock(), data_path=str(nested), enabled=True)
        await pt._save_local_data(SAMPLE_PHISHTANK_DATA)
        assert nested.exists()


# ---------------------------------------------------------------------------
# PhishTankEntry
# ---------------------------------------------------------------------------


class TestPhishTankEntry:
    """Tests for PhishTankEntry dataclass."""

    def test_entry_creation(self):
        entry = PhishTankEntry(
            url="https://evil.com",
            phish_id="123",
            submission_time=datetime.now(),
            verified=True,
            online=True,
            target="Test Brand",
        )
        assert entry.url == "https://evil.com"
        assert entry.verified is True
        assert entry.target == "Test Brand"

    def test_entry_default_target(self):
        entry = PhishTankEntry(
            url="https://evil.com",
            phish_id="456",
            submission_time=datetime.now(),
            verified=False,
            online=True,
        )
        assert entry.target == ""
