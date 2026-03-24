# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for API input validation in sources endpoints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.endpoints.sources import SourceCreateRequest, SourceUpdateRequest


class TestSourceInputValidation:
    """Tests for Source API input validation."""

    # ── Valid Input Tests ───────────────────────────────────────────────────

    def test_valid_source_create_request(self) -> None:
        """Valid source creation request should pass validation."""
        request = SourceCreateRequest(
            id="test-source",
            name="Test Source",
            url="https://example.com/feed.xml",
        )
        assert request.id == "test-source"
        assert request.name == "Test Source"
        assert request.url == "https://example.com/feed.xml"

    def test_valid_url_with_path(self) -> None:
        """URL with path should be accepted."""
        request = SourceCreateRequest(
            id="test",
            name="Test",
            url="https://example.com/path/to/feed.xml",
        )
        assert "path/to/feed.xml" in request.url

    def test_valid_url_with_query_params(self) -> None:
        """URL with query parameters should be accepted."""
        request = SourceCreateRequest(
            id="test",
            name="Test",
            url="https://example.com/feed?type=rss&lang=en",
        )
        assert "type=rss" in request.url

    def test_valid_url_with_port(self) -> None:
        """URL with port should be accepted."""
        request = SourceCreateRequest(
            id="test",
            name="Test",
            url="https://example.com:8443/feed.xml",
        )
        assert ":8443" in request.url

    # ── URL Scheme Validation Tests ─────────────────────────────────────────

    def test_reject_file_scheme(self) -> None:
        """file:// scheme should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="file:///etc/passwd",
            )
        assert "http or https" in str(exc_info.value).lower()

    def test_reject_ftp_scheme(self) -> None:
        """ftp:// scheme should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="ftp://example.com/file",
            )
        assert "http or https" in str(exc_info.value).lower()

    def test_reject_javascript_scheme(self) -> None:
        """javascript: scheme should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="javascript:alert(1)",
            )
        assert "http or https" in str(exc_info.value).lower()

    def test_reject_data_scheme(self) -> None:
        """data: scheme should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="data:text/html,<script>alert(1)</script>",
            )
        assert "http or https" in str(exc_info.value).lower()

    def test_reject_url_without_scheme(self) -> None:
        """URL without scheme should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="example.com/feed",
            )
        assert "scheme" in str(exc_info.value).lower()

    # ── Dangerous Host Blocking Tests ───────────────────────────────────────

    def test_reject_aws_metadata_ip(self) -> None:
        """AWS metadata IP should be blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="http://169.254.169.254/latest/meta-data/",
            )
        assert "blocked" in str(exc_info.value).lower()

    def test_reject_localhost(self) -> None:
        """localhost should be blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="http://localhost/admin",
            )
        assert "blocked" in str(exc_info.value).lower()

    def test_reject_127_0_0_1(self) -> None:
        """127.0.0.1 should be blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="http://127.0.0.1/admin",
            )
        assert "blocked" in str(exc_info.value).lower()

    def test_reject_gcp_metadata_hostname(self) -> None:
        """GCP metadata hostname should be blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="Test",
                url="http://metadata.google.internal/computeMetadata/v1/",
            )
        assert "blocked" in str(exc_info.value).lower()

    # ── Empty Field Validation Tests ────────────────────────────────────────

    def test_reject_empty_id(self) -> None:
        """Empty id should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="",
                name="Test",
                url="https://example.com/feed",
            )
        assert "empty" in str(exc_info.value).lower()

    def test_reject_whitespace_only_id(self) -> None:
        """Whitespace-only id should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="   ",
                name="Test",
                url="https://example.com/feed",
            )
        assert "empty" in str(exc_info.value).lower()

    def test_reject_empty_name(self) -> None:
        """Empty name should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="",
                url="https://example.com/feed",
            )
        assert "empty" in str(exc_info.value).lower()

    def test_reject_whitespace_only_name(self) -> None:
        """Whitespace-only name should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceCreateRequest(
                id="test",
                name="   ",
                url="https://example.com/feed",
            )
        assert "empty" in str(exc_info.value).lower()

    # ── Field Trimming Tests ────────────────────────────────────────────────

    def test_id_is_trimmed(self) -> None:
        """ID should be trimmed of whitespace."""
        request = SourceCreateRequest(
            id="  test-id  ",
            name="Test",
            url="https://example.com/feed",
        )
        assert request.id == "test-id"

    def test_name_is_trimmed(self) -> None:
        """Name should be trimmed of whitespace."""
        request = SourceCreateRequest(
            id="test",
            name="  Test Name  ",
            url="https://example.com/feed",
        )
        assert request.name == "Test Name"

    # ── Update Request Validation Tests ──────────────────────────────────────

    def test_update_request_valid_url(self) -> None:
        """Valid URL in update request should pass."""
        request = SourceUpdateRequest(url="https://example.com/new-feed")
        assert request.url == "https://example.com/new-feed"

    def test_update_request_rejects_invalid_url(self) -> None:
        """Invalid URL in update request should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceUpdateRequest(url="file:///etc/passwd")
        assert "http or https" in str(exc_info.value).lower()

    def test_update_request_rejects_blocked_host(self) -> None:
        """Blocked host in update request should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceUpdateRequest(url="http://169.254.169.254/")
        assert "blocked" in str(exc_info.value).lower()

    def test_update_request_none_url_is_valid(self) -> None:
        """None URL in update request should be valid (no update)."""
        request = SourceUpdateRequest()
        assert request.url is None

    # ── Optional Field Tests ────────────────────────────────────────────────

    def test_optional_fields_defaults(self) -> None:
        """Optional fields should have correct defaults."""
        request = SourceCreateRequest(
            id="test",
            name="Test",
            url="https://example.com/feed",
        )
        assert request.source_type == "rss"
        assert request.enabled is True
        assert request.interval_minutes == 30
        assert request.per_host_concurrency == 2
        assert request.credibility is None
        assert request.tier is None

    def test_custom_optional_fields(self) -> None:
        """Custom optional field values should be accepted."""
        request = SourceCreateRequest(
            id="test",
            name="Test",
            url="https://example.com/feed",
            source_type="atom",
            enabled=False,
            interval_minutes=60,
            per_host_concurrency=5,
            credibility=0.8,
            tier=2,
        )
        assert request.source_type == "atom"
        assert request.enabled is False
        assert request.interval_minutes == 60
        assert request.per_host_concurrency == 5
        assert request.credibility == 0.8
        assert request.tier == 2

    # ── Interval Validation Tests ───────────────────────────────────────────

    def test_interval_minimum_5_minutes(self) -> None:
        """Interval below 5 minutes should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                interval_minutes=4,
            )

    def test_interval_maximum_1440_minutes(self) -> None:
        """Interval above 1440 minutes (24h) should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                interval_minutes=1441,
            )

    # ── Credibility Validation Tests ────────────────────────────────────────

    def test_credibility_minimum_0(self) -> None:
        """Credibility below 0 should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                credibility=-0.1,
            )

    def test_credibility_maximum_1(self) -> None:
        """Credibility above 1 should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                credibility=1.1,
            )

    # ── Tier Validation Tests ───────────────────────────────────────────────

    def test_tier_minimum_1(self) -> None:
        """Tier below 1 should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                tier=0,
            )

    def test_tier_maximum_3(self) -> None:
        """Tier above 3 should be rejected."""
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                id="test",
                name="Test",
                url="https://example.com/feed",
                tier=4,
            )
