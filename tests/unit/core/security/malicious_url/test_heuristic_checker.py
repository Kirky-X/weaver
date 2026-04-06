# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HeuristicChecker."""

import pytest

from core.security.malicious_url.heuristic_checker import HeuristicChecker
from core.security.models import CheckSource, URLRisk


class TestHeuristicChecker:
    """Tests for heuristic URL analysis."""

    @pytest.fixture
    def checker(self) -> HeuristicChecker:
        """Create heuristic checker instance."""
        return HeuristicChecker(enabled=True)

    @pytest.fixture
    def disabled_checker(self) -> HeuristicChecker:
        """Create disabled heuristic checker."""
        return HeuristicChecker(enabled=False)

    # ── Safe URLs ────────────────────────────────────────────────────────

    def test_safe_normal_url(self, checker: HeuristicChecker) -> None:
        """Normal URL should be safe."""
        result = checker.check("https://example.com/path")

        assert result.source == CheckSource.HEURISTIC
        assert result.risk == URLRisk.SAFE

    def test_safe_url_with_query(self, checker: HeuristicChecker) -> None:
        """URL with normal query string should be safe."""
        result = checker.check("https://example.com/search?q=hello&page=1")

        assert result.risk == URLRisk.SAFE

    def test_safe_subdomain(self, checker: HeuristicChecker) -> None:
        """Subdomain should be safe."""
        result = checker.check("https://blog.example.com/post/123")

        assert result.risk == URLRisk.SAFE

    # ── Encoding Obfuscation ─────────────────────────────────────────────

    def test_url_double_encoding(self, checker: HeuristicChecker) -> None:
        """URL with double encoding should be flagged."""
        # Double encoded URL (%25 = encoded %)
        result = checker.check("https://example.com/path%252Fto")

        assert result.risk in (URLRisk.MEDIUM, URLRisk.HIGH)

    def test_url_with_null_byte(self, checker: HeuristicChecker) -> None:
        """URL with null byte injection should be flagged."""
        result = checker.check("https://example.com/path%00.html")

        assert result.risk == URLRisk.HIGH

    def test_url_with_directory_traversal(self, checker: HeuristicChecker) -> None:
        """URL with directory traversal encoding should be flagged."""
        result = checker.check("https://example.com/path%2e%2e%2fetc")

        assert result.risk == URLRisk.HIGH

    # ── Suspicious Keywords ───────────────────────────────────────────────

    def test_single_suspicious_keyword(self, checker: HeuristicChecker) -> None:
        """URL with single suspicious keyword."""
        result = checker.check("https://example.com/login")

        assert result.risk == URLRisk.MEDIUM
        # Check the warning is in details
        assert result.details.get("warnings")
        assert any("login" in w.lower() for w in result.details["warnings"])

    def test_multiple_suspicious_keywords(self, checker: HeuristicChecker) -> None:
        """URL with multiple suspicious keywords."""
        result = checker.check("https://secure-login-verify.example.com/account")

        assert result.risk == URLRisk.HIGH

    def test_keywords_in_domain(self, checker: HeuristicChecker) -> None:
        """Suspicious keywords in domain."""
        result = checker.check("https://secure-login-verify.com/path")

        assert result.risk in (URLRisk.MEDIUM, URLRisk.HIGH)

    # ── Domain Anomalies ──────────────────────────────────────────────────

    def test_excessive_subdomains(self, checker: HeuristicChecker) -> None:
        """URL with too many subdomains."""
        result = checker.check("https://a.b.c.d.e.f.g.example.com/path")

        assert result.risk in (URLRisk.MEDIUM, URLRisk.HIGH)

    def test_very_long_domain_label(self, checker: HeuristicChecker) -> None:
        """URL with extremely long domain label."""
        long_label = "a" * 70
        result = checker.check(f"https://{long_label}.example.com/path")

        assert result.risk in (URLRisk.MEDIUM, URLRisk.HIGH)

    def test_punycode_domain(self, checker: HeuristicChecker) -> None:
        """Punycode domain should be flagged."""
        result = checker.check("https://xn--example-6q4a.com/path")

        assert result.risk in (URLRisk.MEDIUM, URLRisk.HIGH)

    def test_url_shortener(self, checker: HeuristicChecker) -> None:
        """URL shortener should be low risk."""
        result = checker.check("https://bit.ly/abc123")

        assert result.risk == URLRisk.LOW
        # Check warning is in details
        assert result.details.get("warnings")
        assert any("shortener" in w.lower() for w in result.details["warnings"])

    # ── Port Detection ────────────────────────────────────────────────────

    def test_suspicious_port_ssh(self, checker: HeuristicChecker) -> None:
        """URL with SSH port."""
        result = checker.check("https://example.com:22/path")

        assert result.risk == URLRisk.HIGH
        # Check port is in details
        assert result.details.get("warnings")
        assert any("22" in w for w in result.details["warnings"])

    def test_suspicious_port_rdp(self, checker: HeuristicChecker) -> None:
        """URL with RDP port."""
        result = checker.check("https://example.com:3389/path")

        assert result.risk == URLRisk.HIGH

    def test_non_standard_port(self, checker: HeuristicChecker) -> None:
        """URL with non-standard high port."""
        result = checker.check("https://example.com:55000/path")

        assert result.risk == URLRisk.MEDIUM

    def test_standard_port_safe(self, checker: HeuristicChecker) -> None:
        """URL with standard ports should be safe."""
        result = checker.check("https://example.com:443/path")

        assert result.risk == URLRisk.SAFE

    # ── URL Length ────────────────────────────────────────────────────────

    def test_very_long_url(self, checker: HeuristicChecker) -> None:
        """URL that is extremely long."""
        long_path = "/" + "a" * 2100
        result = checker.check(f"https://example.com{long_path}")

        assert result.risk == URLRisk.MEDIUM

    def test_long_url(self, checker: HeuristicChecker) -> None:
        """URL that is long."""
        long_path = "/" + "a" * 1100
        result = checker.check(f"https://example.com{long_path}")

        assert result.risk == URLRisk.LOW

    # ── Disabled Checker ──────────────────────────────────────────────────

    def test_disabled_returns_safe(self, disabled_checker: HeuristicChecker) -> None:
        """Disabled checker should return safe for all URLs."""
        result = disabled_checker.check("https://malicious-phishing.example.com/steal")

        assert result.risk == URLRisk.SAFE
        assert "disabled" in result.message.lower()

    # ── Edge Cases ────────────────────────────────────────────────────────

    def test_invalid_url(self, checker: HeuristicChecker) -> None:
        """Invalid URL handling - parses as relative URL."""
        result = checker.check("not a url")

        assert result.source == CheckSource.HEURISTIC
        # "not a url" parses as a relative URL, no scheme so it's treated as safe
        assert result.risk in (URLRisk.SAFE, URLRisk.MEDIUM)

    def test_empty_url(self, checker: HeuristicChecker) -> None:
        """Empty URL handling."""
        result = checker.check("")

        assert result.source == CheckSource.HEURISTIC
        # Empty URL is valid but has no warnings
        assert result.risk in (URLRisk.SAFE, URLRisk.MEDIUM)
