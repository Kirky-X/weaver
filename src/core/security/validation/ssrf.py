# Copyright (c) 2026 KirkyX. All Rights Reserved
"""SSRF (Server-Side Request Forgery) protection checker.

This module provides SSRF protection by blocking requests to:
- Private IP address ranges (RFC 1918)
- Link-local addresses
- Cloud metadata endpoints (AWS, GCP, Azure)
- Localhost/loopback addresses
- Non-HTTP/HTTPS protocols
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.observability.logging import get_logger

log = get_logger("security.ssrf")


class SSRFError(Exception):
    """Raised when URL fails SSRF validation."""

    def __init__(self, message: str, url: str | None = None):
        self.message = message
        self.url = url
        super().__init__(self.message)


@dataclass
class SSRFChecker:
    """Validates URLs to prevent SSRF attacks.

    This checker blocks requests to internal network resources
    and cloud metadata endpoints.

    Example:
        checker = SSRFChecker()
        try:
            await checker.validate("https://example.com/path")
        except SSRFError as e:
            log.warning("url_blocked", url=e.url, reason=e.message)
    """

    ALLOWED_SCHEMES: set[str] = field(default_factory=lambda: {"http", "https"})

    BLOCKED_IP_RANGES: list[str] = field(
        default_factory=lambda: [
            "10.0.0.0/8",  # Private network (Class A)
            "172.16.0.0/12",  # Private network (Class B)
            "192.168.0.0/16",  # Private network (Class C)
            "169.254.0.0/16",  # Link-local (AWS EC2 metadata)
            "127.0.0.0/8",  # Loopback
            "0.0.0.0/8",  # Current network
            "224.0.0.0/4",  # Multicast
            "240.0.0.0/4",  # Reserved
            "255.255.255.255/32",  # Broadcast
            "::1/128",  # IPv6 loopback
            "fe80::/10",  # IPv6 link-local
            "fc00::/7",  # IPv6 unique local
            "::/128",  # IPv6 unspecified
        ]
    )

    BLOCKED_METADATA_HOSTS: set[str] = field(
        default_factory=lambda: {
            "metadata.google.internal",  # GCP metadata
            "metadata",  # GCP metadata (short)
            "169.254.169.254",  # AWS/Azure metadata IP
            "100.100.100.200",  # Alibaba Cloud metadata
        }
    )

    _blocked_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Initialize cached IP network objects."""
        self._blocked_networks = [
            ipaddress.ip_network(cidr, strict=False) for cidr in self.BLOCKED_IP_RANGES
        ]

    async def validate(self, url: str) -> str:
        """Validate a URL for SSRF safety.

        Args:
            url: The URL to validate.

        Returns:
            The validated URL (unchanged).

        Raises:
            SSRFError: If the URL is potentially dangerous.
        """
        parsed = self._parse_url(url)
        self._validate_scheme(parsed.scheme, url)
        self._validate_metadata_host(parsed.hostname or "", url)
        await self._validate_ip_address(parsed.hostname or "", url)

        log.debug("ssrf_check_passed", url=url)
        return url

    def _parse_url(self, url: str) -> urlparse:
        """Parse URL and validate basic structure.

        Args:
            url: URL to parse.

        Returns:
            Parsed URL object.

        Raises:
            SSRFError: If URL is malformed.
        """
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise SSRFError(f"Malformed URL: {e}", url) from e

        scheme_lower = parsed.scheme.lower()
        if scheme_lower and scheme_lower not in self.ALLOWED_SCHEMES:
            raise SSRFError(
                f"URL scheme '{parsed.scheme}' is not allowed. Only HTTP and HTTPS are permitted.",
                url,
            )

        if not parsed.scheme:
            raise SSRFError("URL must include a scheme (http:// or https://)", url)

        if not parsed.hostname:
            raise SSRFError("URL must include a hostname", url)

        return parsed

    def _validate_scheme(self, scheme: str, url: str) -> None:
        """Validate URL scheme.

        Args:
            scheme: URL scheme to validate.
            url: Original URL for error message.

        Raises:
            SSRFError: If scheme is not allowed.
        """
        if scheme.lower() not in self.ALLOWED_SCHEMES:
            raise SSRFError(
                f"URL scheme '{scheme}' is not allowed. Only HTTP and HTTPS are permitted.",
                url,
            )

    def _validate_metadata_host(self, hostname: str, url: str) -> None:
        """Check if hostname is a known metadata endpoint.

        Args:
            hostname: Hostname to check.
            url: Original URL for error message.

        Raises:
            SSRFError: If hostname is a metadata endpoint.
        """
        if hostname.lower() in self.BLOCKED_METADATA_HOSTS:
            raise SSRFError(
                f"Access to cloud metadata endpoint '{hostname}' is blocked",
                url,
            )

    async def _validate_ip_address(self, hostname: str, url: str) -> None:
        """Resolve hostname and validate IP address.

        Args:
            hostname: Hostname to resolve.
            url: Original URL for error message.

        Raises:
            SSRFError: If IP address is in blocked range.
        """
        # Try to parse as IP address directly
        try:
            ip = ipaddress.ip_address(hostname)
            self._check_blocked_ip(ip, url)
            return
        except ValueError:
            pass  # Not an IP address, continue with DNS resolution
        except SSRFError:
            raise

        # Perform DNS resolution for hostnames
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            addr_infos = await loop.getaddrinfo(hostname, None)

            for family, _, _, _, sockaddr in addr_infos:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    self._check_blocked_ip(ip, url)
                except ValueError:
                    continue

        except socket.gaierror as e:
            log.debug("dns_resolution_skipped", hostname=hostname, error=str(e))
        except SSRFError:
            raise
        except Exception as e:
            log.warning("dns_resolution_error", hostname=hostname, error=str(e))

    def _check_blocked_ip(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address, url: str
    ) -> None:
        """Check if IP address falls in blocked ranges.

        Args:
            ip: IP address to check.
            url: Original URL for error message.

        Raises:
            SSRFError: If IP is in blocked range.
        """
        for network in self._blocked_networks:
            if ip in network:
                raise SSRFError(
                    f"Access to private/internal IP address {ip} is blocked",
                    url,
                )

    def is_safe_url(self, url: str) -> bool:
        """Check if a URL is safe synchronously (without DNS resolution).

        This is a fast synchronous check that only validates:
        - URL scheme
        - Known metadata hosts
        - Direct IP addresses in blocked ranges

        For full validation including DNS resolution, use async validate().

        Args:
            url: URL to check.

        Returns:
            True if URL passes basic safety checks, False otherwise.
        """
        try:
            parsed = self._parse_url(url)
            self._validate_scheme(parsed.scheme, url)
            self._validate_metadata_host(parsed.hostname or "", url)

            # Check if hostname is a direct IP address
            try:
                ip = ipaddress.ip_address(parsed.hostname or "")
                self._check_blocked_ip(ip, url)
            except ValueError:
                pass  # Not an IP address

            return True
        except SSRFError:
            return False
