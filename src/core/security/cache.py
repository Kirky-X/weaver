# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Cache layer for URL security check results.

Provides differential caching with different TTL based on risk level:
- Safe results: cached longer (default 6 hours)
- Malicious results: cached shorter (default 15 minutes)
"""

import hashlib
import json
from typing import Any

from core.observability.logging import get_logger
from core.security.models import URLRisk

log = get_logger(__name__)


class URLSecurityCache:
    """Cache for URL security check results.

    Uses Redis for distributed caching with differential TTL:
    - Safe results: cached for longer period
    - Malicious results: cached for shorter period

    Attributes:
        _redis: Redis client instance.
        _safe_ttl: TTL in seconds for safe results.
        _malicious_ttl: TTL in seconds for malicious results.
        _enabled: Whether caching is enabled.
    """

    def __init__(
        self,
        cache_client: Any,
        safe_ttl: int = 21600,  # 6 hours
        malicious_ttl: int = 900,  # 15 minutes
        enabled: bool = True,
    ) -> None:
        """Initialize the cache.

        Args:
            cache_client: Redis client instance.
            safe_ttl: TTL in seconds for safe results.
            malicious_ttl: TTL in seconds for malicious results.
            enabled: Whether caching is enabled.
        """
        self._redis = cache_client
        self._safe_ttl = safe_ttl
        self._malicious_ttl = malicious_ttl
        self._enabled = enabled
        self._prefix = "url_security:"

    def _get_key(self, url: str) -> str:
        """Generate cache key from URL.

        Uses SHA256 hash of URL for consistent key length.

        Args:
            url: The URL to hash.

        Returns:
            Cache key string.
        """
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"{self._prefix}{url_hash}"

    async def get(self, url: str) -> dict[str, Any] | None:
        """Get cached result for URL.

        Args:
            url: The URL to look up.

        Returns:
            Cached result dict or None if not found.
        """
        if not self._enabled:
            return None

        try:
            key = self._get_key(url)

            # Check if redis client has the get method
            if hasattr(self._redis, "get"):
                cached = await self._redis.get(key)
                if cached:
                    return json.loads(cached)
            elif hasattr(self._redis, "execute_command"):
                # Fallback for different redis client interfaces
                cached = await self._redis.execute_command("GET", key)
                if cached:
                    return json.loads(cached)

            return None

        except Exception as e:
            log.warning("cache_get_error", url=url, error=str(e))
            return None

    async def set(self, url: str, result: dict[str, Any], risk: str) -> None:
        """Cache result for URL with appropriate TTL.

        Args:
            url: The URL being cached.
            result: The validation result to cache.
            risk: The risk level (determines TTL).
        """
        if not self._enabled:
            return

        try:
            key = self._get_key(url)
            ttl = self._get_ttl_for_risk(risk)
            value = json.dumps(result)

            # Use appropriate redis method
            if hasattr(self._redis, "setex"):
                await self._redis.setex(key, ttl, value)
            elif hasattr(self._redis, "execute_command"):
                await self._redis.execute_command("SETEX", key, ttl, value)

            log.debug("cache_set", url=url, risk=risk, ttl=ttl)

        except Exception as e:
            log.warning("cache_set_error", url=url, error=str(e))

    async def delete(self, url: str) -> None:
        """Delete cached result for URL.

        Args:
            url: The URL to delete from cache.
        """
        if not self._enabled:
            return

        try:
            key = self._get_key(url)

            if hasattr(self._redis, "delete"):
                await self._redis.delete(key)
            elif hasattr(self._redis, "execute_command"):
                await self._redis.execute_command("DEL", key)

        except Exception as e:
            log.warning("cache_delete_error", url=url, error=str(e))

    async def clear_all(self) -> None:
        """Clear all cached URL security results."""
        if not self._enabled:
            return

        try:
            # Find all keys with our prefix using scan_iter (non-blocking)
            keys_to_delete = []
            async for key in self._redis.scan_iter(f"{self._prefix}*"):
                keys_to_delete.append(key)

            if keys_to_delete:
                await self._redis.delete(*keys_to_delete)

            log.info("cache_cleared")

        except Exception as e:
            log.warning("cache_clear_error", error=str(e))

    def _get_ttl_for_risk(self, risk: str) -> int:
        """Get TTL based on risk level.

        Args:
            risk: The risk level string.

        Returns:
            TTL in seconds.
        """
        if risk in (URLRisk.HIGH.value, URLRisk.BLOCKED.value):
            return self._malicious_ttl
        return self._safe_ttl
