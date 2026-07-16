# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""URL Security Validator facade.

Provides a unified interface for URL security checking that orchestrates
multiple security checkers in a pipeline:

1. Cache lookup
2. SSRF protection
3. URLhaus API (if configured)
4. PhishTank blacklist
5. Heuristic analysis
6. SSL certificate verification
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from config.settings import URLSecuritySettings
from core.observability import get_logger
from core.security.cache import URLSecurityCache
from core.security.models import CheckResult, CheckSource, URLRisk, ValidationResult
from core.security.validation.malicious_url.heuristic_checker import HeuristicChecker
from core.security.validation.malicious_url.phishtank_sync import PhishTankSync
from core.security.validation.malicious_url.ssl_verifier import SSLVerifier
from core.security.validation.malicious_url.urlhaus_client import URLhausClient
from core.security.validation.ssrf import SSRFChecker, SSRFError

if TYPE_CHECKING:
    from modules.ingestion import HttpxFetcher

log = get_logger(__name__)


@dataclass
class URLValidatorConfig:
    """Configuration for URL validator."""

    enabled: bool = True
    urlhaus_api_key: str = ""
    urlhaus_api_timeout: float = 5.0
    phishtank_enabled: bool = True
    phishtank_data_url: str = "https://data.phishtank.com/data/online-valid.json"
    heuristic_enabled: bool = True
    ssl_verify_enabled: bool = True
    cache_enabled: bool = True
    cache_safe_ttl: int = 21600
    cache_malicious_ttl: int = 900

    @classmethod
    def from_settings(cls, settings: URLSecuritySettings) -> "URLValidatorConfig":
        """Create config from settings.

        Args:
            settings: URLSecuritySettings instance.

        Returns:
            URLValidatorConfig instance.
        """
        return cls(
            enabled=settings.enabled,
            urlhaus_api_key=settings.urlhaus_api_key,
            urlhaus_api_timeout=settings.urlhaus_api_timeout,
            phishtank_enabled=settings.phishtank_enabled,
            phishtank_data_url=settings.phishtank_data_url,
            heuristic_enabled=settings.heuristic_enabled,
            ssl_verify_enabled=settings.ssl_verify_enabled,
            cache_enabled=settings.cache_enabled,
            cache_safe_ttl=settings.cache_safe_ttl_seconds,
            cache_malicious_ttl=settings.cache_malicious_ttl_seconds,
        )


class URLValidator:
    """URL security validator facade.

    Orchestrates multiple security checkers to provide comprehensive
    URL security validation.

    Example:
        validator = URLValidator(config, fetcher, cache_client)
        await validator.initialize()

        result = await validator.validate("https://example.com")
        if result.is_safe:
            print("URL is safe")
        else:
            print(f"URL is unsafe: {result.primary_reason}")
    """

    def __init__(
        self,
        config: URLValidatorConfig,
        fetcher: "HttpxFetcher",
        cache_client: Any = None,
    ) -> None:
        """Initialize URL validator.

        Args:
            config: Validator configuration.
            fetcher: HttpxFetcher instance for HTTP requests.
            cache_client: Optional Redis client for caching.
        """
        self._config = config
        self._fetcher = fetcher

        # Initialize cache
        self._cache = URLSecurityCache(
            cache_client=cache_client,
            safe_ttl=config.cache_safe_ttl,
            malicious_ttl=config.cache_malicious_ttl,
            enabled=config.cache_enabled,
        )

        # Initialize SSRF checker
        self._ssrf_checker = SSRFChecker()

        # Initialize URLhaus client (if API key configured)
        self._urlhaus_client: URLhausClient | None = None
        if config.urlhaus_api_key:
            self._urlhaus_client = URLhausClient(
                api_key=config.urlhaus_api_key,
                fetcher=fetcher,
                timeout=config.urlhaus_api_timeout,
            )

        # Initialize PhishTank sync
        self._phishtank: PhishTankSync | None = None
        if config.phishtank_enabled:
            self._phishtank = PhishTankSync(
                fetcher=fetcher,
                enabled=True,
                data_url=config.phishtank_data_url,
            )

        # Initialize heuristic checker
        self._heuristic = HeuristicChecker(enabled=config.heuristic_enabled)

        # Initialize SSL verifier
        self._ssl_verifier = SSLVerifier(enabled=config.ssl_verify_enabled)

    async def initialize(self) -> None:
        """Initialize validator: load PhishTank data."""
        if self._phishtank:
            await self._phishtank.initialize()
        log.info("url_validator_initialized")

    async def validate(self, url: str) -> ValidationResult:
        """Validate URL security.

        Args:
            url: URL to validate.

        Returns:
            ValidationResult with complete validation outcome.
        """
        if not self._config.enabled:
            return self._disabled_result(url)

        # 1. Check cache
        cached = await self._cache.get(url)
        if cached:
            return ValidationResult(
                url=url,
                risk=URLRisk(cached["risk"]),
                is_safe=cached["is_safe"],
                checks=[
                    CheckResult(
                        source=CheckSource.CACHE,
                        risk=URLRisk(cached["risk"]),
                        message="Cached result",
                    )
                ],
                cached=True,
            )

        checks: list[CheckResult] = []

        # 2. SSRF check
        ssrf_result = await self._run_ssrf(url)
        checks.append(ssrf_result)
        if ssrf_result.risk == URLRisk.BLOCKED:
            return self._build_result(url, checks)

        # 3. URLhaus API check
        should_run_local = True
        if self._urlhaus_client:
            urlhaus_result = await self._run_urlhaus(url)
            checks.append(urlhaus_result)

            if urlhaus_result.risk == URLRisk.BLOCKED:
                return self._build_result(url, checks)

            if urlhaus_result.risk == URLRisk.SAFE:
                should_run_local = False

        # 4. Local checks
        if should_run_local:
            # PhishTank
            if self._phishtank:
                pt_result = self._phishtank.check(url)
                checks.append(pt_result)
                if pt_result.risk == URLRisk.BLOCKED:
                    return self._build_result(url, checks)

            # Heuristic
            heuristic_result = self._heuristic.check(url)
            checks.append(heuristic_result)

        # 5. SSL verification
        ssl_result = await self._ssl_verifier.check(url)
        checks.append(ssl_result)

        return self._build_result(url, checks)

    async def _run_ssrf(self, url: str) -> CheckResult:
        """Run SSRF check.

        Args:
            url: URL to check.

        Returns:
            CheckResult from SSRF checker.
        """
        try:
            await self._ssrf_checker.validate(url)
            return CheckResult(
                source=CheckSource.SSRF,
                risk=URLRisk.SAFE,
                message="SSRF check passed",
            )
        except SSRFError as e:
            return CheckResult(
                source=CheckSource.SSRF,
                risk=URLRisk.BLOCKED,
                message=e.message,
                details={"url": e.url},
            )

    async def _run_urlhaus(self, url: str) -> CheckResult:
        """Run URLhaus API check.

        Args:
            url: URL to check.

        Returns:
            CheckResult from URLhaus client.
        """
        if not self._urlhaus_client:
            return CheckResult(
                source=CheckSource.URLHAUS_API,
                risk=URLRisk.SAFE,
                message="URLhaus not configured",
            )

        response = await self._urlhaus_client.check(url)
        return self._urlhaus_client.to_check_result(response)

    def _build_result(self, url: str, checks: list[CheckResult]) -> ValidationResult:
        """Build final validation result.

        Args:
            url: URL that was validated.
            checks: List of check results.

        Returns:
            Aggregated ValidationResult.
        """
        # Find highest risk
        max_risk = URLRisk.SAFE
        for check in checks:
            if check.risk > max_risk:
                max_risk = check.risk

        is_safe = max_risk in (URLRisk.SAFE, URLRisk.LOW)

        result = ValidationResult(
            url=url,
            risk=max_risk,
            is_safe=is_safe,
            checks=checks,
        )

        # Cache result asynchronously (fire-and-forget with error logging)
        _cache_task = asyncio.create_task(
            self._cache.set(
                url=url,
                result={"risk": max_risk.value, "is_safe": is_safe},
                risk=max_risk.value,
            )
        )
        _cache_task.add_done_callback(
            lambda t: (
                log.warning("url_validation_cache_failed", error=str(t.exception()))
                if t.exception()
                else None
            )
        )

        return result

    def _disabled_result(self, url: str) -> ValidationResult:
        """Return result when validation is disabled.

        Args:
            url: URL that was requested.

        Returns:
            Safe ValidationResult.
        """
        return ValidationResult(
            url=url,
            risk=URLRisk.SAFE,
            is_safe=True,
            checks=[
                CheckResult(
                    source=CheckSource.CACHE,
                    risk=URLRisk.SAFE,
                    message="Security check disabled",
                )
            ],
        )

    async def sync_phishtank(self) -> None:
        """Manually trigger PhishTank data sync."""
        if self._phishtank:
            await self._phishtank.sync()

    @property
    def ssrf_checker(self) -> SSRFChecker:
        """Get SSRF checker for direct access.

        Returns:
            SSRFChecker instance.
        """
        return self._ssrf_checker
