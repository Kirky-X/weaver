# Copyright (c) 2026 KirkyX. All Rights Reserved
"""URLhaus API client for real-time malicious URL lookup.

URLhaus is a free service from abuse.ch that provides a database of
malicious URLs. This client integrates with their API for real-time
checking.

API Documentation: https://urlhaus-api.abuse.ch/
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.observability.logging import get_logger
from core.security.models import CheckResult, CheckSource, URLRisk

log = get_logger("security.urlhaus")


class URLhausStatus(Enum):
    """URLhaus API query status."""

    MALICIOUS = "malicious"
    """URL found in database as malicious."""

    SAFE = "safe"
    """URL not found in database."""

    UNKNOWN = "unknown"
    """Unexpected response from API."""

    ERROR = "error"
    """API request failed."""


@dataclass
class URLhausResponse:
    """URLhaus API response data."""

    status: URLhausStatus
    """Query result status."""

    threat_type: str = ""
    """Type of threat (e.g., malware_download, phishing)."""

    threat_url: str = ""
    """The malicious URL as recorded in URLhaus."""

    error_message: str = ""
    """Error message if status is ERROR."""


class URLhausClient:
    """Client for URLhaus API.

    Provides real-time malicious URL lookup using URLhaus database.

    Attributes:
        API_URL: URLhaus API endpoint.
        _api_key: API key for authentication.
        _fetcher: HttpxFetcher for making requests.
    """

    API_URL = "https://urlhaus-api.abuse.ch/v1/url/"

    def __init__(self, api_key: str, fetcher: Any) -> None:
        """Initialize URLhaus client.

        Args:
            api_key: URLhaus API key.
            fetcher: HttpxFetcher instance for HTTP requests.
        """
        self._api_key = api_key
        self._fetcher = fetcher

    async def check(self, url: str) -> URLhausResponse:
        """Check URL against URLhaus database.

        Args:
            url: The URL to check.

        Returns:
            URLhausResponse with the check result.
        """
        if not self._api_key:
            return URLhausResponse(
                status=URLhausStatus.ERROR,
                error_message="URLhaus API key not configured",
            )

        try:
            status_code, response_text, _ = await self._fetcher.post(
                self.API_URL,
                data={"url": url},
                headers={"Auth-Key": self._api_key},
            )

            if status_code == 429:
                log.warning("urlhaus_rate_limited", url=url)
                return URLhausResponse(
                    status=URLhausStatus.ERROR,
                    error_message="Rate limited",
                )

            if status_code != 200:
                log.warning("urlhaus_http_error", url=url, status=status_code)
                return URLhausResponse(
                    status=URLhausStatus.ERROR,
                    error_message=f"HTTP {status_code}",
                )

            import json

            data = json.loads(response_text)
            return self._parse_response(data)

        except Exception as e:
            log.warning("urlhaus_error", url=url, error=str(e))
            return URLhausResponse(
                status=URLhausStatus.ERROR,
                error_message=str(e),
            )

    def _parse_response(self, data: dict[str, Any]) -> URLhausResponse:
        """Parse URLhaus API response.

        Args:
            data: JSON response from API.

        Returns:
            Parsed URLhausResponse.
        """
        query_status = data.get("query_status", "")

        if query_status == "ok":
            # URL found in malicious database
            return URLhausResponse(
                status=URLhausStatus.MALICIOUS,
                threat_type=data.get("threat", "unknown"),
                threat_url=data.get("url", ""),
            )

        if query_status == "no_results":
            return URLhausResponse(status=URLhausStatus.SAFE)

        if query_status == "invalid_api_key":
            log.error("urlhaus_invalid_api_key")
            return URLhausResponse(
                status=URLhausStatus.ERROR,
                error_message="Invalid API key",
            )

        return URLhausResponse(
            status=URLhausStatus.UNKNOWN,
            error_message=f"Unknown status: {query_status}",
        )

    def to_check_result(self, response: URLhausResponse) -> CheckResult:
        """Convert URLhaus response to CheckResult.

        Args:
            response: URLhaus API response.

        Returns:
            CheckResult for use in validation pipeline.
        """
        if response.status == URLhausStatus.MALICIOUS:
            return CheckResult(
                source=CheckSource.URLHAUS_API,
                risk=URLRisk.BLOCKED,
                message=f"Found in URLhaus database: {response.threat_type}",
                details={"threat_type": response.threat_type},
            )

        if response.status == URLhausStatus.SAFE:
            return CheckResult(
                source=CheckSource.URLHAUS_API,
                risk=URLRisk.SAFE,
                message="Not found in URLhaus database",
            )

        # ERROR or UNKNOWN - indicate fallback needed
        return CheckResult(
            source=CheckSource.URLHAUS_API,
            risk=URLRisk.LOW,
            message=f"API check failed: {response.error_message}",
            details={"error": response.error_message, "should_fallback": True},
        )
