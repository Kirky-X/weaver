# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Heuristic URL security checker.

Detects suspicious URL patterns including:
- URL encoding obfuscation
- Suspicious keywords
- Domain structure anomalies
- Suspicious ports
- Abnormal URL length
"""

import re
from urllib.parse import ParseResult, unquote, urlparse

from core.observability.logging import get_logger
from core.security.models import CheckResult, CheckSource, URLRisk

log = get_logger("security.heuristic")


# Default suspicious keywords
DEFAULT_SUSPICIOUS_KEYWORDS: set[str] = {
    "login",
    "signin",
    "sign-in",
    "verify",
    "verification",
    "secure",
    "security",
    "account",
    "update",
    "confirm",
    "password",
    "credential",
    "auth",
    "authenticate",
    "banking",
    "wallet",
    "payment",
    "transaction",
    "phishing",
    "scam",
    "fraud",
    "suspended",
    "locked",
    "alert",
    "warning",
    "urgent",
    "limited",
    "expire",
}

# Default suspicious ports
DEFAULT_SUSPICIOUS_PORTS: set[int] = {
    22,  # SSH
    23,  # Telnet
    445,  # SMB
    3389,  # RDP
    4444,  # Metasploit
    5555,  # Common malware
    6667,  # IRC (botnet C2)
}

# Default URL shortener domains
DEFAULT_SHORTENER_DOMAINS: set[str] = {
    "bit.ly",
    "goo.gl",
    "tinyurl.com",
    "t.co",
    "is.gd",
    "buff.ly",
    "ow.ly",
    "short.link",
    "dlvr.it",
    "cutt.ly",
}


class HeuristicChecker:
    """Heuristic URL security checker.

    Analyzes URLs for suspicious patterns that may indicate
    phishing or malicious intent.
    """

    def __init__(
        self,
        enabled: bool = True,
        check_encoded_chars: bool = True,
        check_suspicious_keywords: bool = True,
        check_domain_structure: bool = True,
        suspicious_keywords: set[str] | None = None,
        suspicious_ports: set[int] | None = None,
        shortener_domains: set[str] | None = None,
    ) -> None:
        """Initialize heuristic checker.

        Args:
            enabled: Whether checking is enabled.
            check_encoded_chars: Check for encoding obfuscation.
            check_suspicious_keywords: Check for suspicious keywords.
            check_domain_structure: Check for domain anomalies.
            suspicious_keywords: Custom set of suspicious keywords.
            suspicious_ports: Custom set of suspicious ports.
            shortener_domains: Custom set of URL shortener domains.
        """
        self._enabled = enabled
        self._check_encoded_chars = check_encoded_chars
        self._check_suspicious_keywords = check_suspicious_keywords
        self._check_domain_structure = check_domain_structure
        self.SUSPICIOUS_KEYWORDS = suspicious_keywords or DEFAULT_SUSPICIOUS_KEYWORDS
        self.SUSPICIOUS_PORTS = suspicious_ports or DEFAULT_SUSPICIOUS_PORTS
        self.SHORTENER_DOMAINS = shortener_domains or DEFAULT_SHORTENER_DOMAINS

    def check(self, url: str) -> CheckResult:
        """Perform heuristic check on URL.

        Args:
            url: URL to check.

        Returns:
            CheckResult with findings.
        """
        if not self._enabled:
            return CheckResult(
                source=CheckSource.HEURISTIC,
                risk=URLRisk.SAFE,
                message="Heuristic check disabled",
            )

        warnings: list[str] = []
        max_risk = URLRisk.SAFE

        try:
            parsed = urlparse(url)
            decoded_url = unquote(unquote(url))  # Double decode
        except Exception:
            return CheckResult(
                source=CheckSource.HEURISTIC,
                risk=URLRisk.MEDIUM,
                message="Failed to parse URL",
            )

        # 1. Encoding obfuscation
        if self._check_encoded_chars:
            risk, warning = self._check_encoding(url, decoded_url)
            if warning:
                warnings.append(warning)
                if risk > max_risk:
                    max_risk = risk

        # 2. Suspicious keywords
        if self._check_suspicious_keywords:
            risk, warning = self._check_keywords(decoded_url)
            if warning:
                warnings.append(warning)
                if risk > max_risk:
                    max_risk = risk

        # 3. Domain structure
        if self._check_domain_structure:
            risk, warning = self._check_domain(parsed)
            if warning:
                warnings.append(warning)
                if risk > max_risk:
                    max_risk = risk

        # 4. Port check
        risk, warning = self._check_port(parsed)
        if warning:
            warnings.append(warning)
            if risk > max_risk:
                max_risk = risk

        # 5. Length check
        risk, warning = self._check_length(url)
        if warning:
            warnings.append(warning)
            if risk > max_risk:
                max_risk = risk

        if not warnings:
            return CheckResult(
                source=CheckSource.HEURISTIC,
                risk=URLRisk.SAFE,
                message="No heuristic warnings",
            )

        return CheckResult(
            source=CheckSource.HEURISTIC,
            risk=max_risk,
            message=f"Found {len(warnings)} heuristic warning(s)",
            details={"warnings": warnings},
        )

    def _check_encoding(self, original: str, decoded: str) -> tuple[URLRisk, str]:
        """Check for URL encoding obfuscation.

        Args:
            original: Original URL.
            decoded: Decoded URL.

        Returns:
            Tuple of (risk, warning message).
        """
        # Double encoding
        if "%" in decoded:
            return URLRisk.MEDIUM, "Double URL encoding detected"

        # Suspicious encoded characters
        suspicious_patterns = [
            (r"%00", "Null byte injection"),
            (r"%0[dD]", "Carriage return injection"),
            (r"%0[aA]", "Line feed injection"),
            (r"%2[eE]%2[eE]", "Directory traversal encoding"),
            (r"%25", "Percent encoding of percent"),
        ]

        for pattern, desc in suspicious_patterns:
            if re.search(pattern, original, re.IGNORECASE):
                return URLRisk.HIGH, desc

        return URLRisk.SAFE, ""

    def _check_keywords(self, decoded_url: str) -> tuple[URLRisk, str]:
        """Check for suspicious keywords.

        Args:
            decoded_url: Decoded URL to check.

        Returns:
            Tuple of (risk, warning message).
        """
        url_lower = decoded_url.lower()
        found_keywords = []

        for keyword in self.SUSPICIOUS_KEYWORDS:
            if keyword in url_lower:
                found_keywords.append(keyword)

        if len(found_keywords) >= 3:
            return (
                URLRisk.HIGH,
                f"Multiple suspicious keywords: {', '.join(found_keywords[:5])}",
            )
        elif len(found_keywords) >= 1:
            return URLRisk.MEDIUM, f"Suspicious keyword found: {found_keywords[0]}"

        return URLRisk.SAFE, ""

    def _check_domain(self, parsed: ParseResult) -> tuple[URLRisk, str]:
        """Check domain structure for anomalies.

        Args:
            parsed: Parsed URL.

        Returns:
            Tuple of (risk, warning message).
        """
        domain = parsed.netloc.lower()

        # Remove port
        if ":" in domain:
            domain = domain.split(":")[0]

        warnings = []

        # Subdomain levels
        parts = domain.split(".")
        if len(parts) > 5:
            warnings.append(f"Excessive subdomain levels: {len(parts)}")

        # Long domain label
        for part in parts:
            if len(part) > 63:
                warnings.append("Domain label exceeds 63 characters")
                break

        # Excessive hyphens
        if domain.count("-") > 5:
            warnings.append("Excessive hyphens in domain")

        # IDN homograph attack
        if "xn--" in domain:
            warnings.append("IDN/punycode domain detected (potential homograph attack)")

        # Numeric subdomain
        if parts and parts[0].isdigit():
            warnings.append("Numeric subdomain detected")

        # URL shortener
        if domain in self.SHORTENER_DOMAINS:
            return URLRisk.LOW, f"URL shortener detected: {domain}"

        if not warnings:
            return URLRisk.SAFE, ""

        if len(warnings) >= 2:
            return URLRisk.HIGH, f"Multiple domain issues: {'; '.join(warnings)}"

        return URLRisk.MEDIUM, warnings[0]

    def _check_port(self, parsed: ParseResult) -> tuple[URLRisk, str]:
        """Check for suspicious ports.

        Args:
            parsed: Parsed URL.

        Returns:
            Tuple of (risk, warning message).
        """
        if not parsed.port:
            return URLRisk.SAFE, ""

        if parsed.port in self.SUSPICIOUS_PORTS:
            return URLRisk.HIGH, f"Suspicious port: {parsed.port}"

        if parsed.port > 49151:
            return URLRisk.MEDIUM, f"Non-standard port: {parsed.port}"

        return URLRisk.SAFE, ""

    def _check_length(self, url: str) -> tuple[URLRisk, str]:
        """Check for abnormal URL length.

        Args:
            url: URL to check.

        Returns:
            Tuple of (risk, warning message).
        """
        url_len = len(url)
        if url_len > 2000:
            return URLRisk.MEDIUM, f"Very long URL: {url_len} characters"
        elif url_len > 1000:
            return URLRisk.LOW, f"Long URL: {url_len} characters"

        return URLRisk.SAFE, ""
