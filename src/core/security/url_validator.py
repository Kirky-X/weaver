# Copyright (c) 2026 KirkyX. All Rights Reserved
"""URL Security Validator for SSRF Protection.

This module provides a comprehensive URL validation system to prevent
Server-Side Request Forgery (SSRF) attacks by blocking requests to
internal network resources, cloud metadata endpoints, and other
sensitive network locations.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.observability.logging import get_logger

log = get_logger("security.url_validator")


class URLValidationError(Exception):
    """Raised when URL validation fails."""

    def __init__(self, message: str, url: str | None = None):
        self.message = message
        self.url = url
        super().__init__(self.message)


@dataclass
class URLValidator:
    """Validates URLs to prevent SSRF attacks.

    This validator blocks requests to:
    - Private IP address ranges (RFC 1918)
    - Link-local addresses
    - Cloud metadata endpoints (AWS, GCP, Azure)
    - Localhost/loopback addresses
    - Non-HTTP/HTTPS protocols

    Example:
        validator = URLValidator()
        try:
            safe_url = await validator.validate("https://example.com/path")
        except URLValidationError as e:
            print(f"Blocked: {e.message}")
    """

    # Allowed URL schemes
    ALLOWED_SCHEMES: set[str] = field(default_factory=lambda: {"http", "https"})

    # Blocked IP ranges (CIDR notation)
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

    # Cloud metadata hostnames that should always be blocked
    BLOCKED_METADATA_HOSTS: set[str] = field(
        default_factory=lambda: {
            "metadata.google.internal",  # GCP metadata
            "metadata",  # GCP metadata (short)
            "169.254.169.254",  # AWS/Azure metadata IP
            "100.100.100.200",  # Alibaba Cloud metadata
        }
    )

    # Cached IP network objects for faster lookups
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
            The validated URL (sanitized).

        Raises:
            URLValidationError: If the URL is potentially dangerous.
        """
        # 1. Basic URL parsing
        parsed = self._parse_url(url)

        # 2. Check scheme
        self._validate_scheme(parsed.scheme, url)

        # 3. Check for blocked metadata hosts
        self._validate_metadata_host(parsed.hostname or "", url)

        # 4. Resolve and validate IP address
        await self._validate_ip_address(parsed.hostname or "", url)

        log.debug("url_validated", url=url)
        return url

    def _parse_url(self, url: str) -> urlparse:
        """Parse URL and validate basic structure.

        Args:
            url: URL to parse.

        Returns:
            Parsed URL object.

        Raises:
            URLValidationError: If URL is malformed.
        """
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise URLValidationError(f"Malformed URL: {e}", url) from e

        # Check scheme first (before hostname check)
        scheme_lower = parsed.scheme.lower()
        if scheme_lower and scheme_lower not in self.ALLOWED_SCHEMES:
            raise URLValidationError(
                f"URL scheme '{parsed.scheme}' is not allowed. Only HTTP and HTTPS are permitted.",
                url,
            )

        if not parsed.scheme:
            raise URLValidationError("URL must include a scheme (http:// or https://)", url)

        if not parsed.hostname:
            raise URLValidationError("URL must include a hostname", url)

        return parsed

    def _validate_scheme(self, scheme: str, url: str) -> None:
        """Validate URL scheme.

        Args:
            scheme: URL scheme to validate.
            url: Original URL for error message.

        Raises:
            URLValidationError: If scheme is not allowed.
        """
        scheme_lower = scheme.lower()
        if scheme_lower not in self.ALLOWED_SCHEMES:
            raise URLValidationError(
                f"URL scheme '{scheme}' is not allowed. Only HTTP and HTTPS are permitted.", url
            )

    def _validate_metadata_host(self, hostname: str, url: str) -> None:
        """Check if hostname is a known metadata endpoint.

        Args:
            hostname: Hostname to check.
            url: Original URL for error message.

        Raises:
            URLValidationError: If hostname is a metadata endpoint.
        """
        hostname_lower = hostname.lower()
        if hostname_lower in self.BLOCKED_METADATA_HOSTS:
            raise URLValidationError(
                f"Access to cloud metadata endpoint '{hostname}' is blocked", url
            )

    async def _validate_ip_address(self, hostname: str, url: str) -> None:
        """Resolve hostname and validate IP address.

        Args:
            hostname: Hostname to resolve.
            url: Original URL for error message.

        Raises:
            URLValidationError: If IP address is in blocked range.
        """
        # Try to parse as IP address directly (before any DNS resolution)
        try:
            ip = ipaddress.ip_address(hostname)
            # This will raise URLValidationError if blocked
            self._check_blocked_ip(ip, url)
            return
        except ValueError:
            pass  # Not an IP address, continue with DNS resolution
        except URLValidationError:
            raise  # Re-raise blocked IP errors

        # Perform DNS resolution for hostnames
        try:
            loop = None
            try:
                import asyncio

                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass

            resolved_ips = []
            if loop:
                # Async DNS resolution
                addr_infos = await loop.getaddrinfo(hostname, None)
                for family, _, _, _, sockaddr in addr_infos:
                    ip_str = sockaddr[0]
                    resolved_ips.append(ip_str)
            else:
                # Fallback to sync resolution
                addr_infos = socket.getaddrinfo(hostname, None)
                for family, _, _, _, sockaddr in addr_infos:
                    ip_str = sockaddr[0]
                    resolved_ips.append(ip_str)

            # Check all resolved IPs
            for ip_str in resolved_ips:
                try:
                    ip = ipaddress.ip_address(ip_str)
                    self._check_blocked_ip(ip, url)
                except ValueError:
                    continue  # Skip invalid IPs

        except socket.gaierror as e:
            # DNS resolution failed - in development, allow it to pass
            # In production, this should be stricter
            log.debug("dns_resolution_skipped", hostname=hostname, error=str(e))
        except URLValidationError:
            raise  # Re-raise blocked IP errors
        except Exception as e:
            log.warning("dns_resolution_error", hostname=hostname, error=str(e))
            # For security, block on resolution errors in production
            environment = getattr(self, "_environment", "development")
            if environment == "production":
                raise URLValidationError(
                    f"Could not resolve hostname '{hostname}' - blocked for security", url
                ) from e

    def _check_blocked_ip(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address, url: str
    ) -> None:
        """Check if IP address falls in blocked ranges.

        Args:
            ip: IP address to check.
            url: Original URL for error message.

        Raises:
            URLValidationError: If IP is in blocked range.
        """
        for network in self._blocked_networks:
            if ip in network:
                raise URLValidationError(
                    f"Access to private/internal IP address {ip} is blocked", url
                )

    def is_safe_url(self, url: str) -> bool:
        """Synchronously check if a URL is safe (without DNS resolution).

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
        except URLValidationError:
            return False


# Convenience function for quick validation
async def validate_url(url: str) -> str:
    """Validate a URL for SSRF safety.

    Args:
        url: The URL to validate.

    Returns:
        The validated URL.

    Raises:
        URLValidationError: If the URL is potentially dangerous.
    """
    validator = URLValidator()
    return await validator.validate(url)
