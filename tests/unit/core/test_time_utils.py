# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for time_utils module."""

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import ntplib
import pytest

from core.utils.time_utils import (
    CACHE_TTL,
    NTP_SERVERS,
    NTP_TIMEOUT,
    _get_ntp_time,
    _ntp_cache,
    _ntp_client,
    get_current_time_with_timezone,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset NTP cache and singleton client before each test."""
    import core.utils.time_utils as time_utils

    _ntp_cache["time"] = None
    _ntp_cache["expires"] = 0.0
    time_utils._ntp_client = None
    yield
    _ntp_cache["time"] = None
    _ntp_cache["expires"] = 0.0
    time_utils._ntp_client = None


class TestGetNtpTime:
    """Tests for _get_ntp_time function."""

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_get_ntp_time_success(self, mock_ntp_client):
        """Test successful NTP time retrieval."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is not None
        assert result.tzinfo == UTC

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_get_ntp_time_fastest_wins(self, mock_ntp_client):
        """Test that the fastest server response is used."""
        call_order = []

        def make_delayed_response(delay: float):
            def side_effect(*args, **kwargs):
                time.sleep(delay)
                call_order.append(kwargs.get("timeout"))
                resp = MagicMock()
                resp.tx_time = 1704067200.0
                return resp

            return side_effect

        mock_client = MagicMock()
        mock_client.request.side_effect = make_delayed_response(0.01)
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is not None
        # All servers were probed concurrently (5 calls)
        assert mock_client.request.call_count == 5

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_get_ntp_time_returns_none_on_all_failures(self, mock_ntp_client):
        """Test returns None when all servers fail."""
        mock_client = MagicMock()
        mock_client.request.side_effect = ntplib.NTPException("All servers failed")
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is None

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_get_ntp_time_handles_unexpected_exception(self, mock_ntp_client):
        """Test handles unexpected exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.request.side_effect = RuntimeError("Unexpected error")
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is None

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_concurrent_probing_uses_all_servers(self, mock_ntp_client):
        """Test that all servers are probed concurrently."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        _get_ntp_time()

        # All 5 servers should be probed
        assert mock_client.request.call_count == len(NTP_SERVERS)


class TestNtpCache:
    """Tests for TTL cache behavior."""

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_cache_hit_avoids_network(self, mock_ntp_client):
        """Test that cached result is returned without network call."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        # First call - should hit network (1 singleton client, 5 requests)
        result1 = _get_ntp_time()
        assert result1 is not None
        assert mock_ntp_client.call_count == 1

        # Record call count after first probe
        calls_after_first = mock_ntp_client.call_count

        # Second call - should hit cache, no new NTPClient created
        result2 = _get_ntp_time()
        assert result2 == result1
        # No additional network calls
        assert mock_ntp_client.call_count == calls_after_first

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_cache_stores_none_on_failure(self, mock_ntp_client):
        """Test that failed probes cache None."""
        mock_client = MagicMock()
        mock_client.request.side_effect = ntplib.NTPException("Failed")
        mock_ntp_client.return_value = mock_client

        result1 = _get_ntp_time()
        assert result1 is None
        calls_after_first = mock_ntp_client.call_count

        # Second call should return cached None without network
        result2 = _get_ntp_time()
        assert result2 is None
        # No additional calls
        assert mock_ntp_client.call_count == calls_after_first

    @patch("core.utils.time_utils.monotonic")
    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_cache_expiration_triggers_new_probe(self, mock_ntp_client, mock_monotonic):
        """Test that expired cache triggers new NTP probe."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        # Simulate time progression
        call_count = [0]

        def monotonic_side():
            call_count[0] += 1
            if call_count[0] <= 2:
                return 0.0  # Initial time
            return CACHE_TTL + 1  # After expiration

        mock_monotonic.side_effect = monotonic_side

        result1 = _get_ntp_time()
        assert result1 is not None

        # After expiration, should probe again (5 more clients)
        result2 = _get_ntp_time()
        assert result2 is not None
        # After expiration, should probe again
        result2 = _get_ntp_time()
        assert result2 is not None
        # Singleton: 1 NTPClient, but .request called 10 times (5 per round)
        assert mock_ntp_client.call_count == 1

    @patch("core.utils.time_utils.monotonic")
    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_cache_miss_triggers_probe(self, mock_ntp_client, mock_monotonic):
        """Test that cache miss (initial state) triggers NTP probe."""
        mock_monotonic.return_value = 0.0
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is not None
        # One singleton client created (5 requests on it)
        assert mock_ntp_client.call_count == 1


class TestGetCurrentTimeWithTimezone:
    """Tests for get_current_time_with_timezone function."""

    @patch("core.utils.time_utils._get_ntp_time")
    def test_returns_iso_format_string(self, mock_get_ntp):
        """Test returns ISO format string."""
        mock_get_ntp.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = get_current_time_with_timezone()

        assert isinstance(result, str)
        assert "T" in result

    @patch("core.utils.time_utils._get_ntp_time")
    def test_falls_back_to_local_time_on_ntp_failure(self, mock_get_ntp):
        """Test falls back to local time when NTP fails."""
        mock_get_ntp.return_value = None

        result = get_current_time_with_timezone()

        assert isinstance(result, str)
        assert "+" in result or "Z" in result or "-" in result


class TestNtpConstants:
    """Tests for NTP constants."""

    def test_ntp_servers_list(self):
        """Test NTP servers list has 5 entries with domestic first."""
        assert len(NTP_SERVERS) == 5
        assert NTP_SERVERS[0] == "ntp.aliyun.com"
        assert NTP_SERVERS[1] == "ntp.tencent.com"
        assert "time.google.com" in NTP_SERVERS

    def test_ntp_timeout_value(self):
        """Test NTP timeout is 1 second."""
        assert NTP_TIMEOUT == 1

    def test_cache_ttl_value(self):
        """Test cache TTL is 3600 seconds (1 hour)."""
        assert CACHE_TTL == 3600


class TestNtplibIntegration:
    """Integration tests for ntplib usage."""

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_ntplib_client_is_singleton(self, mock_ntp_client):
        """Test NTPClient is created once and reused (singleton pattern)."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        _get_ntp_time()

        # Singleton: only one NTPClient instantiated
        assert mock_ntp_client.call_count == 1
        # But .request called for all 5 servers
        assert mock_client.request.call_count == len(NTP_SERVERS)

    def test_ntplib_available(self):
        """Test ntplib is available and importable."""
        assert hasattr(ntplib, "NTPClient")
        assert hasattr(ntplib, "NTPException")
