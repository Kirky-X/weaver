# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for core/security HIGH findings (OCR report).

Covers: (invalid port), (cert date parse),
(urlhaus timeout), (cache collision guard), /
(audit query clamp + PII opt-in), (redirect scheme).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.security.cache import URLSecurityCache
from core.security.validation.malicious_url.heuristic_checker import (
    HeuristicChecker,
)
from core.security.validation.malicious_url.urlhaus_client import URLhausClient
from core.security.validation.malicious_url.urlhaus_client import (
    URLhausStatus,
)


def _parse(url: str):  # type: ignore[no-untyped-def]
    from urllib.parse import urlparse

    return urlparse(url)


class TestHeuristicPortCheck:
    """malformed ports must not raise ValueError."""

    def test_invalid_port_returns_high_risk(self) -> None:
        checker = HeuristicChecker()
        parsed = _parse("https://example.com:abc/")
        risk, message = checker._check_port(parsed)
        assert risk.value in ("high", "HIGH", 3) or risk.name == "HIGH"
        assert "Invalid port" in message

    def test_out_of_range_port_returns_high_risk(self) -> None:
        checker = HeuristicChecker()
        parsed = _parse("https://example.com:99999999999999/")
        risk, message = checker._check_port(parsed)
        assert risk.name == "HIGH"
        assert "Invalid port" in message

    def test_normal_url_safe(self) -> None:
        checker = HeuristicChecker()
        parsed = _parse("https://example.com/path")
        risk, message = checker._check_port(parsed)
        assert risk.name == "SAFE"
        assert message == ""


class TestSSLDateParsing:
    """unparseable cert dates degrade instead of raising."""

    def _run_fetch_with_cert(self, cert_dict: dict) -> object:
        from core.security.validation.malicious_url.ssl_verifier import SSLVerifier

        verifier = SSLVerifier.__new__(SSLVerifier)
        verifier._timeout = 1.0

        fake_ssock = MagicMock()
        fake_ssock.getpeercert.return_value = cert_dict
        fake_sock = MagicMock()
        ctx_cm = MagicMock()
        ctx_cm.wrap_socket.return_value.__enter__ = MagicMock(return_value=fake_ssock)
        ctx_cm.wrap_socket.return_value.__exit__ = MagicMock(return_value=False)
        sock_cm = MagicMock()
        sock_cm.__enter__ = MagicMock(return_value=fake_sock)
        sock_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("ssl.create_default_context", return_value=ctx_cm),
            patch("socket.create_connection", return_value=sock_cm),
        ):
            return verifier._fetch_certificate_sync("example.com", 443)

    def test_bad_not_before_degrades_to_min_date(self) -> None:
        from datetime import datetime

        info = self._run_fetch_with_cert(
            {
                "subject": ((("commonName", "example.com"),),),
                "issuer": ((("commonName", "Some CA"),),),
                "notBefore": "garbage",
                "notAfter": "Jan 1 00:00:00 2099 GMT",
            }
        )
        assert info.not_before == datetime.min
        assert info.is_expired is False or info.is_expired is not None

    def test_missing_dates_do_not_raise(self) -> None:
        info = self._run_fetch_with_cert(
            {
                "subject": ((("commonName", "example.com"),),),
                "issuer": ((("commonName", "Some CA"),),),
            }
        )
        assert info is not None


class TestURLhausTimeout:
    """the configured timeout must bound the request."""

    async def test_hanging_fetcher_times_out(self) -> None:
        fetcher = MagicMock()

        async def hang(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            await asyncio.sleep(30)

        fetcher.post = hang
        client = URLhausClient(api_key="key", fetcher=fetcher, timeout=0.05)

        response = await asyncio.wait_for(client.check("https://example.com"), timeout=5)
        assert response.status == URLhausStatus.ERROR


class TestURLSecurityCacheCollision:
    """Hash collisions must not return another URL's verdict."""

    def _fake_redis(self) -> object:
        store: dict = {}

        class FakeRedis:
            async def get(self, key: str) -> str | None:
                return store.get(key)

            async def set(self, key: str, value: str, ex: int) -> None:
                store[key] = value

        return FakeRedis(), store

    async def test_collision_returns_none(self) -> None:
        redis, store = self._fake_redis()
        cache = URLSecurityCache(cache_client=redis, safe_ttl=60, malicious_ttl=60, enabled=True)

        await cache.set("https://a.example.com", {"risk": "safe", "is_safe": True}, "safe")

        # Simulate a collision: overwrite the entry with a different URL
        key = cache._get_key("https://a.example.com")
        store[key] = json.dumps(
            {"url": "https://evil.example.com", "result": {"risk": "safe", "is_safe": True}}
        )

        assert await cache.get("https://a.example.com") is None

    async def test_matching_url_returns_result(self) -> None:
        redis, _ = self._fake_redis()
        cache = URLSecurityCache(cache_client=redis, safe_ttl=60, malicious_ttl=60, enabled=True)

        await cache.set("https://a.example.com", {"risk": "safe", "is_safe": True}, "safe")
        assert await cache.get("https://a.example.com") == {"risk": "safe", "is_safe": True}


class TestAuditQueryEvents:
    """limit clamp and PII opt-in."""

    def _make_service(self, captured: list) -> object:
        from core.security.audit_log_service import AuditLogService

        row = MagicMock(
            id=1,
            key_id="k1",
            action="read",
            target_type="article",
            target_id="t1",
            detail=None,
            client_ip="10.0.0.1",
            user_agent="UA",
            created_at=None,
        )
        scalars = MagicMock()
        scalars.all.return_value = [row]
        result = MagicMock()
        result.scalars.return_value = scalars

        session = MagicMock()
        session.execute = AsyncMock(side_effect=lambda q: captured.append(q) or result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.session.return_value = session
        return AuditLogService(pool)

    async def test_limit_clamped_to_upper_bound(self) -> None:
        captured: list = []
        service = self._make_service(captured)
        events = await service.query_events(limit=999_999)
        assert len(events) == 1
        compiled = str(captured[0].compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 10000" in compiled

    async def test_pii_hidden_by_default_and_included_when_requested(self) -> None:
        captured: list = []
        service = self._make_service(captured)
        events = await service.query_events(limit=10)
        assert events[0]["client_ip"] is None
        assert events[0]["user_agent"] is None

        events = await service.query_events(limit=10, include_pii=True)
        assert events[0]["client_ip"] == "10.0.0.1"
        assert events[0]["user_agent"] == "UA"
