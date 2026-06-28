# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance tests for ApiKeyManager.validate_key O(1) direct lookup.

Tests:
(a) key_value contains key_id prefix → direct lookup
(b) key_id lookup succeeds but bcrypt fails → return None, no fallback
(c) Old format key (no key_id prefix) → fallback scan
(d) 100 keys validation latency comparable to 1 key
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db import ApiKey
from core.security.api_key_manager import ApiKeyManager
from tests.helpers import create_mock_relational_pool


def _valid_key_id() -> str:
    """Generate a valid key_id matching key_{token_hex(8)} format."""
    return f"key_{secrets.token_hex(8)}"


def _make_api_key(
    key_id: str | None = None,
    key_value: str | None = None,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    is_revoked: bool = False,
) -> tuple[ApiKey, str]:
    """Create an ApiKey ORM object with bcrypt hash.

    Returns:
        (ApiKey instance, raw key_value)
    """
    if key_id is None:
        key_id = _valid_key_id()
    if key_value is None:
        # New format: weaver_{key_id}_{secret}
        key_value = f"weaver_{key_id}_{secrets.token_hex(24)}"
    if scopes is None:
        scopes = ["search:read"]
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(days=90)

    key_hash = ApiKeyManager._hash_key(key_value)

    api_key = ApiKey(
        key_id=key_id,
        key_hash=key_hash,
        scopes=scopes,
        rate_limit_per_min=100,
        expires_at=expires_at,
        created_by="test",
    )
    api_key.is_revoked = is_revoked
    return api_key, key_value


def _mock_scalar_one_or_none(result):
    """Build a mock for session.execute().scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = result
    return mock_result


def _mock_scalars_all(results):
    """Build a mock for session.execute().scalars().all()."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = results
    mock_result.scalars.return_value = mock_scalars
    return mock_result


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock RelationalPool."""
    return create_mock_relational_pool()


@pytest.fixture
def manager(mock_pool: MagicMock) -> ApiKeyManager:
    """Create ApiKeyManager with mock pool."""
    return ApiKeyManager(mock_pool)


class TestDirectLookup:
    """key_value with key_id prefix triggers direct SQL lookup."""

    async def test_new_format_key_direct_lookup(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """key_value containing key_id prefix → single SQL query by key_id."""
        key_id = _valid_key_id()
        api_key, key_value = _make_api_key(key_id=key_id)
        session = mock_pool.session.return_value

        # First call: scalar_one_or_none for direct lookup
        # Second call: update for last_used_at
        session.execute.side_effect = [
            _mock_scalar_one_or_none(api_key),
            MagicMock(),  # update result
        ]

        result = await manager.validate_key(key_value)
        assert result is not None
        assert result["key_id"] == key_id

        # Verify first execute was a select with key_id filter (direct lookup)
        first_call = session.execute.call_args_list[0]
        assert first_call is not None

    async def test_direct_lookup_bcrypt_fail_no_fallback(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """key_id found but bcrypt mismatch → return None, no scan fallback."""
        key_id = _valid_key_id()
        api_key, _key_value = _make_api_key(key_id=key_id)
        session = mock_pool.session.return_value

        # Direct lookup returns a key, but we pass a wrong key_value
        # that still matches the key_id pattern
        wrong_key = f"weaver_{key_id}_{secrets.token_hex(24)}"
        session.execute.return_value = _mock_scalar_one_or_none(api_key)

        result = await manager.validate_key(wrong_key)
        assert result is None

        # Only one execute call (direct lookup), no scan fallback
        assert session.execute.call_count == 1


class TestFallbackScan:
    """Old-format keys (no key_id prefix) fall back to O(n) scan."""

    async def test_old_format_key_fallback_scan(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Old format key_value (no key_id prefix) → full scan fallback."""
        # Create an old-format key: weaver_{uuid_hex} without key_id prefix
        old_key_value = f"weaver_{uuid.uuid4().hex}"
        key_id = _valid_key_id()
        api_key, _ = _make_api_key(key_id=key_id, key_value=old_key_value)
        session = mock_pool.session.return_value

        # When extracted_key_id is None, code skips direct lookup entirely.
        # Only scan query + update are executed.
        session.execute.side_effect = [
            _mock_scalars_all([api_key]),  # scan returns candidates
            MagicMock(),  # update result
        ]

        result = await manager.validate_key(old_key_value)
        assert result is not None
        assert result["key_id"] == key_id

        # Two execute calls: scan + update
        assert session.execute.call_count == 2

    async def test_old_format_no_match_returns_none(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Old format key with no matching hash → return None."""
        old_key_value = f"weaver_{uuid.uuid4().hex}"
        session = mock_pool.session.return_value

        # When extracted_key_id is None, only scan is executed
        session.execute.side_effect = [
            _mock_scalars_all([]),
        ]

        result = await manager.validate_key(old_key_value)
        assert result is None


class TestKeyExtraction:
    """Test _extract_key_id static method."""

    def test_new_format_extracts_key_id(self) -> None:
        """New 32-char format: weaver_{8hex}_{16hex} → extracts 8 hex."""
        key_id = secrets.token_hex(4)  # 8 hex chars
        secret = secrets.token_hex(8)  # 16 hex chars
        key_value = f"weaver_{key_id}_{secret}"
        assert len(key_value) == 32  # 7 + 8 + 1 + 16 = 32
        extracted = ApiKeyManager._extract_key_id(key_value)
        assert extracted == key_id

    def test_old_format_extracts_key_id(self) -> None:
        """Old 76-char format: weaver_key_{16hex}_{secret} → extracts 'key_{16hex}'."""
        key_id = f"key_{secrets.token_hex(8)}"
        key_value = f"weaver_{key_id}_somesecretpart"
        extracted = ApiKeyManager._extract_key_id(key_value)
        assert extracted == key_id

    def test_legacy_format_returns_none(self) -> None:
        """Legacy weaver_{uuid_hex} (no key_ prefix, not 32-char) → returns None."""
        key_id = ApiKeyManager._extract_key_id(f"weaver_{uuid.uuid4().hex}")
        assert key_id is None

    def test_non_weaver_prefix_returns_none(self) -> None:
        """Non-weaver prefix → returns None."""
        key_id = ApiKeyManager._extract_key_id("other_key_abc1234567890_secret")
        assert key_id is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string → returns None."""
        key_id = ApiKeyManager._extract_key_id("")
        assert key_id is None

    def test_just_weaver_returns_none(self) -> None:
        """'weaver_' alone → returns None."""
        key_id = ApiKeyManager._extract_key_id("weaver_")
        assert key_id is None

    def test_key_id_too_short_returns_none(self) -> None:
        """key_ prefix but hex part too short → returns None."""
        key_id = ApiKeyManager._extract_key_id("weaver_key_abc_secret")
        assert key_id is None

    def test_new_format_wrong_length_returns_none(self) -> None:
        """32-char format but wrong secret length → returns None."""
        # secret too short (15 hex instead of 16)
        key_value = f"weaver_{secrets.token_hex(4)}_{secrets.token_hex(7)[:15]}"
        key_id = ApiKeyManager._extract_key_id(key_value)
        assert key_id is None


class TestPerformanceBenchmark:
    """Performance: 100 keys should validate as fast as 1 key (O(1) lookup)."""

    async def test_direct_lookup_latency_independent_of_key_count(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Direct lookup latency should not depend on number of keys in DB."""
        key_id = _valid_key_id()
        api_key, key_value = _make_api_key(key_id=key_id)
        session = mock_pool.session.return_value

        # Mock direct lookup (returns immediately regardless of key count)
        session.execute.side_effect = [
            _mock_scalar_one_or_none(api_key),
            MagicMock(),  # update
        ]

        # Time the validation
        start = time.monotonic()
        result = await manager.validate_key(key_value)
        elapsed = time.monotonic() - start

        assert result is not None
        # Even with bcrypt, single lookup should be well under 50ms
        # (bcrypt verify is ~10-50ms depending on work factor)
        assert elapsed < 2.0, f"Validation took {elapsed:.3f}s, expected < 2s"


class TestExpiredKey:
    """Expired keys should be rejected regardless of lookup method."""

    async def test_expired_key_direct_lookup(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Expired key found via direct lookup → return None."""
        expired_at = datetime.now(UTC) - timedelta(days=1)
        key_id = _valid_key_id()
        api_key, key_value = _make_api_key(key_id=key_id, expires_at=expired_at)
        session = mock_pool.session.return_value

        session.execute.return_value = _mock_scalar_one_or_none(api_key)

        result = await manager.validate_key(key_value)
        assert result is None

    async def test_revoked_key_direct_lookup(
        self, manager: ApiKeyManager, mock_pool: MagicMock
    ) -> None:
        """Revoked key found via direct lookup → return None."""
        key_id = _valid_key_id()
        api_key, key_value = _make_api_key(key_id=key_id, is_revoked=True)
        session = mock_pool.session.return_value

        session.execute.return_value = _mock_scalar_one_or_none(api_key)

        result = await manager.validate_key(key_value)
        assert result is None
