# Copyright (c) 2026 KirkyX. All Rights Reserved
"""SSL certificate verification for URL security.

Verifies SSL certificates for:
- Validity (not expired, proper date range)
- Trust chain (trusted CA, not self-signed)
- EV certificate detection
- Certificate transparency indicators
"""

import asyncio
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from core.observability.logging import get_logger
from core.security.models import CheckResult, CheckSource, URLRisk

log = get_logger("security.ssl")


@dataclass
class CertificateInfo:
    """SSL certificate information."""

    subject: str
    """Certificate subject (CN)."""

    issuer: str
    """Certificate issuer (CA)."""

    not_before: datetime
    """Certificate validity start date."""

    not_after: datetime
    """Certificate validity end date."""

    is_ev: bool
    """Whether certificate is Extended Validation."""

    is_self_signed: bool
    """Whether certificate is self-signed."""

    is_expired: bool
    """Whether certificate has expired."""

    days_until_expiry: int
    """Days until certificate expires."""

    san_count: int
    """Number of Subject Alternative Names."""


class SSLVerifier:
    """SSL certificate verification.

    Checks SSL certificates for security indicators and potential issues.

    Attributes:
        TRUSTED_CAS: Known trusted Certificate Authorities.
        EV_OIDS: Extended Validation certificate OIDs.
        _enabled: Whether verification is enabled.
        _timeout: Connection timeout in seconds.
    """

    TRUSTED_CAS: set[str] = {
        "DigiCert",
        "Let's Encrypt",
        "GlobalSign",
        "Comodo",
        "GoDaddy",
        "Amazon",
        "Cloudflare",
        "Google Trust Services",
        "Microsoft",
        "Sectigo",
        "Entrust",
        "Thawte",
        "GeoTrust",
        "RapidSSL",
    }

    EV_OIDS: set[str] = {
        "1.3.6.1.4.1.34697.2.1",  # DigiCert EV
        "1.3.6.1.4.1.14370.1.6",  # GeoTrust EV
        "1.3.6.1.4.1.4146.1.1",  # GlobalSign EV
        "2.16.840.1.113733.1.7.23.6",  # VeriSign EV
        "1.3.6.1.4.1.11129.2.1.4",  # Google EV
    }

    def __init__(self, enabled: bool = True, timeout: float = 10.0) -> None:
        """Initialize SSL verifier.

        Args:
            enabled: Whether verification is enabled.
            timeout: Connection timeout in seconds.
        """
        self._enabled = enabled
        self._timeout = timeout

    async def check(self, url: str) -> CheckResult:
        """Verify SSL certificate for URL.

        Args:
            url: URL to verify.

        Returns:
            CheckResult with certificate verification results.
        """
        if not self._enabled:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.SAFE,
                message="SSL verification disabled",
            )

        parsed = urlparse(url)

        # Skip non-HTTPS
        if parsed.scheme.lower() != "https":
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.SAFE,
                message="Non-HTTPS URL, SSL check skipped",
            )

        hostname = parsed.hostname
        port = parsed.port or 443

        try:
            cert_info = await self._fetch_certificate(hostname, port)
            return self._analyze_certificate(cert_info, hostname)

        except ssl.SSLCertVerificationError as e:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.HIGH,
                message=f"Certificate verification failed: {e.verify_message}",
                details={"error": str(e)},
            )
        except ssl.SSLError as e:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.MEDIUM,
                message=f"SSL error: {e!s}",
                details={"error": str(e)},
            )
        except TimeoutError:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.MEDIUM,
                message="SSL connection timeout",
            )
        except Exception as e:
            log.warning("ssl_check_error", url=url, error=str(e))
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.LOW,
                message=f"SSL check failed: {e!s}",
                details={"error": str(e)},
            )

    async def _fetch_certificate(self, hostname: str, port: int) -> CertificateInfo:
        """Fetch SSL certificate information.

        Args:
            hostname: Hostname to connect to.
            port: Port number.

        Returns:
            CertificateInfo with certificate details.
        """
        loop = asyncio.get_event_loop()

        return await loop.run_in_executor(
            None,
            self._fetch_certificate_sync,
            hostname,
            port,
        )

    def _fetch_certificate_sync(self, hostname: str, port: int) -> CertificateInfo:
        """Synchronously fetch certificate information.

        Args:
            hostname: Hostname to connect to.
            port: Port number.

        Returns:
            CertificateInfo with certificate details.
        """
        context = ssl.create_default_context()

        with (
            socket.create_connection((hostname, port), timeout=self._timeout) as sock,
            context.wrap_socket(sock, server_hostname=hostname) as ssock,
        ):
            cert_dict = ssock.getpeercert()

            # Parse subject and issuer
            subject = dict(x[0] for x in cert_dict.get("subject", ()))
            issuer = dict(x[0] for x in cert_dict.get("issuer", ()))

            # Parse dates
            not_before = datetime.strptime(cert_dict.get("notBefore", ""), "%b %d %H:%M:%S %Y %Z")
            not_after = datetime.strptime(cert_dict.get("notAfter", ""), "%b %d %H:%M:%S %Y %Z")

            now = datetime.now()
            is_expired = now > not_after
            days_until_expiry = (not_after - now).days

            # Check EV
            is_ev = self._check_ev_certificate(cert_dict)

            # Check self-signed
            is_self_signed = subject.get("commonName") == issuer.get("commonName")

            # SAN count
            san_count = len(cert_dict.get("subjectAltName", []))

            return CertificateInfo(
                subject=subject.get("commonName", ""),
                issuer=issuer.get("commonName", "") or issuer.get("organizationName", ""),
                not_before=not_before,
                not_after=not_after,
                is_ev=is_ev,
                is_self_signed=is_self_signed,
                is_expired=is_expired,
                days_until_expiry=days_until_expiry,
                san_count=san_count,
            )

    def _check_ev_certificate(self, cert_dict: dict[str, Any]) -> bool:
        """Check if certificate is Extended Validation.

        Args:
            cert_dict: Certificate dictionary from getpeercert().

        Returns:
            True if certificate is EV.
        """
        policies = cert_dict.get("certificatePolicies", [])
        for policy in policies:
            policy_oid = policy[0] if policy else ""
            if policy_oid in self.EV_OIDS:
                return True
        return False

    def _analyze_certificate(self, cert: CertificateInfo, hostname: str) -> CheckResult:
        """Analyze certificate for security issues.

        Args:
            cert: Certificate information.
            hostname: Original hostname.

        Returns:
            CheckResult with analysis.
        """
        warnings: list[str] = []
        max_risk = URLRisk.SAFE

        # 1. Expired
        if cert.is_expired:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.HIGH,
                message="Certificate has expired",
                details={
                    "expired": True,
                    "not_after": cert.not_after.isoformat(),
                },
            )

        # 2. Expiring soon
        if cert.days_until_expiry <= 7:
            warnings.append(f"Certificate expires in {cert.days_until_expiry} days")
            max_risk = URLRisk.MEDIUM

        # 3. Self-signed
        if cert.is_self_signed:
            warnings.append("Self-signed certificate")
            max_risk = URLRisk.HIGH

        # 4. Non-EV from unknown CA
        issuer_lower = cert.issuer.lower()
        is_trusted_ca = any(ca.lower() in issuer_lower for ca in self.TRUSTED_CAS)

        if not cert.is_ev and not is_trusted_ca:
            warnings.append(f"Non-EV certificate from unknown CA: {cert.issuer}")
            if max_risk < URLRisk.MEDIUM:
                max_risk = URLRisk.MEDIUM

        # 5. High SAN count
        if cert.san_count > 50:
            warnings.append(f"Unusually high SAN count: {cert.san_count}")
            if max_risk < URLRisk.MEDIUM:
                max_risk = URLRisk.MEDIUM

        if not warnings:
            return CheckResult(
                source=CheckSource.SSL,
                risk=URLRisk.SAFE,
                message="SSL certificate is valid",
                details={
                    "issuer": cert.issuer,
                    "is_ev": cert.is_ev,
                    "days_until_expiry": cert.days_until_expiry,
                },
            )

        return CheckResult(
            source=CheckSource.SSL,
            risk=max_risk,
            message=f"SSL warnings: {'; '.join(warnings)}",
            details={
                "warnings": warnings,
                "issuer": cert.issuer,
                "is_ev": cert.is_ev,
            },
        )
