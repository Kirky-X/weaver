# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for time_utils module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import ntplib
import pytest

from core.utils.time_utils import (
    NTP_SERVERS,
    NTP_TIMEOUT,
    _get_ntp_time,
    get_current_time_with_timezone,
)


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
    def test_get_ntp_time_fallback_to_second_server(self, mock_ntp_client):
        """Test fallback to second server when first fails."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.side_effect = [
            ntplib.NTPException("Server 1 failed"),
            mock_response,
        ]
        mock_ntp_client.return_value = mock_client

        result = _get_ntp_time()

        assert result is not None
        assert mock_client.request.call_count == 2

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
        """Test NTP servers list is not empty."""
        assert len(NTP_SERVERS) > 0
        assert "pool.ntp.org" in NTP_SERVERS

    def test_ntp_timeout_value(self):
        """Test NTP timeout is reasonable."""
        assert NTP_TIMEOUT > 0
        assert NTP_TIMEOUT <= 10


class TestNtplibIntegration:
    """Integration tests for ntplib usage."""

    @patch("core.utils.time_utils.ntplib.NTPClient")
    def test_ntplib_client_created_correctly(self, mock_ntp_client):
        """Test NTPClient is created correctly."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.tx_time = 1704067200.0
        mock_client.request.return_value = mock_response
        mock_ntp_client.return_value = mock_client

        _get_ntp_time()

        mock_ntp_client.assert_called_once()

    def test_ntplib_available(self):
        """Test ntplib is available and importable."""
        assert hasattr(ntplib, "NTPClient")
        assert hasattr(ntplib, "NTPException")
