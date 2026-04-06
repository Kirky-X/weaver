# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SSLVerifier."""

from unittest.mock import MagicMock, patch

import pytest

from core.security.malicious_url.ssl_verifier import SSLVerifier
from core.security.models import CheckSource, URLRisk


class TestSSLVerifier:
    """Tests for SSL certificate verification."""

    @pytest.fixture
    def verifier(self) -> SSLVerifier:
        """Create SSL verifier instance."""
        return SSLVerifier(enabled=True)

    @pytest.fixture
    def disabled_verifier(self) -> SSLVerifier:
        """Create disabled SSL verifier."""
        return SSLVerifier(enabled=False)

    # ── Non-HTTPS URLs ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_http_url_safe(self, verifier: SSLVerifier) -> None:
        """HTTP URL should be safe (no SSL)."""
        result = await verifier.check("http://example.com")

        assert result.source == CheckSource.SSL
        assert result.risk == URLRisk.SAFE
        assert "non-https" in result.message.lower()

    # ── Disabled Verifier ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_disabled_returns_safe(self, disabled_verifier: SSLVerifier) -> None:
        """Disabled verifier should return safe."""
        result = await disabled_verifier.check("https://example.com")

        assert result.risk == URLRisk.SAFE
        assert "disabled" in result.message.lower()

    # ── SSL Errors ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_self_signed_certificate(self, verifier: SSLVerifier) -> None:
        """Self-signed certificate should be flagged."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="example.com",  # Same as subject = self-signed
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=365),
                is_ev=False,
                is_self_signed=True,
                is_expired=False,
                days_until_expiry=365,
                san_count=1,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.HIGH
            assert "self-signed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_expired_certificate(self, verifier: SSLVerifier) -> None:
        """Expired certificate should be flagged as high risk."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="DigiCert",
                not_before=datetime.now() - timedelta(days=365),
                not_after=datetime.now() - timedelta(days=1),  # Expired
                is_ev=False,
                is_self_signed=False,
                is_expired=True,
                days_until_expiry=-1,
                san_count=1,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.HIGH
            assert "expired" in result.message.lower()

    @pytest.mark.asyncio
    async def test_expiring_soon_certificate(self, verifier: SSLVerifier) -> None:
        """Certificate expiring soon should be medium risk."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="DigiCert",
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=5),  # Expiring in 5 days
                is_ev=False,
                is_self_signed=False,
                is_expired=False,
                days_until_expiry=5,
                san_count=1,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.MEDIUM
            assert "expires" in result.message.lower()

    @pytest.mark.asyncio
    async def test_ev_certificate_safe(self, verifier: SSLVerifier) -> None:
        """EV certificate should be safe."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="DigiCert",
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=365),
                is_ev=True,
                is_self_signed=False,
                is_expired=False,
                days_until_expiry=365,
                san_count=1,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.SAFE
            assert result.details.get("is_ev") is True

    @pytest.mark.asyncio
    async def test_valid_certificate_from_trusted_ca(self, verifier: SSLVerifier) -> None:
        """Valid certificate from trusted CA should be safe."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="Let's Encrypt",
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=90),
                is_ev=False,
                is_self_signed=False,
                is_expired=False,
                days_until_expiry=90,
                san_count=2,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.SAFE

    @pytest.mark.asyncio
    async def test_unknown_ca_warning(self, verifier: SSLVerifier) -> None:
        """Non-EV certificate from unknown CA should be medium risk."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="Unknown CA Corp",
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=365),
                is_ev=False,
                is_self_signed=False,
                is_expired=False,
                days_until_expiry=365,
                san_count=1,
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.MEDIUM
            assert "unknown ca" in result.message.lower()

    # ── Connection Errors ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_connection_error(self, verifier: SSLVerifier) -> None:
        """Connection error should return low risk."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            mock_fetch.side_effect = ConnectionError("Connection refused")

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.LOW
            assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_timeout_error(self, verifier: SSLVerifier) -> None:
        """Timeout error should return medium risk."""
        import socket

        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            mock_fetch.side_effect = TimeoutError("Connection timed out")

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.MEDIUM
            assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_ssl_error(self, verifier: SSLVerifier) -> None:
        """SSL error should return medium risk."""
        import ssl

        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            mock_fetch.side_effect = ssl.SSLError("SSL error")

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.MEDIUM

    @pytest.mark.asyncio
    async def test_ssl_cert_verification_error(self, verifier: SSLVerifier) -> None:
        """SSL certificate verification error should return high risk."""
        import ssl

        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            error = ssl.SSLCertVerificationError("Certificate verify failed")
            error.verify_message = "hostname mismatch"
            mock_fetch.side_effect = error

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.HIGH

    # ── Edge Cases ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_invalid_url(self, verifier: SSLVerifier) -> None:
        """Invalid URL handling - non-https URLs are skipped."""
        result = await verifier.check("not a url")

        assert result.source == CheckSource.SSL
        # Non-HTTPS URLs are skipped and return SAFE
        assert result.risk == URLRisk.SAFE

    @pytest.mark.asyncio
    async def test_high_san_count(self, verifier: SSLVerifier) -> None:
        """High SAN count should be flagged."""
        with patch.object(verifier, "_fetch_certificate") as mock_fetch:
            from datetime import datetime, timedelta

            from core.security.malicious_url.ssl_verifier import CertificateInfo

            mock_fetch.return_value = CertificateInfo(
                subject="example.com",
                issuer="DigiCert",
                not_before=datetime.now() - timedelta(days=30),
                not_after=datetime.now() + timedelta(days=365),
                is_ev=False,
                is_self_signed=False,
                is_expired=False,
                days_until_expiry=365,
                san_count=100,  # High SAN count
            )

            result = await verifier.check("https://example.com")

            assert result.risk == URLRisk.MEDIUM
            assert "san" in result.message.lower()
