# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for pure ASGI middleware helpers.

 regression: ``redact_query`` previously truncated the query string
BEFORE masking sensitive values, so a value split by the truncation boundary
leaked its first half into logs.
"""

from __future__ import annotations

from api.middleware.asgi import _MAX_QUERY_LOG_LEN, redact_query


class TestRedactQuerySensitiveValues:
    """Sensitive values must never survive redaction, at any truncation point."""

    def test_sensitive_value_masked_before_truncation(self) -> None:
        # Truncation lands INSIDE the password value; truncating first would
        # leak "password=SuperSec...".
        query = "ok=1&password=SuperSecretValue1234567890"
        max_len = 20

        result = redact_query(query, max_len=max_len)

        assert "SuperSec" not in result
        assert "SuperSecretValue1234567890" not in result

    def test_token_value_split_at_boundary_not_leaked(self) -> None:
        query = "a=1&token=sk-live-abcdef0123456789&tail=z"
        max_len = 12

        result = redact_query(query, max_len=max_len)

        assert "sk-live" not in result
        assert "abcdef" not in result

    def test_all_sensitive_key_variants_masked(self) -> None:
        query = "api_key=A1&apikey=B2&access_token=C3&secret=&auth=E5&signature=F6"

        result = redact_query(query, max_len=1000)

        for value in ("A1", "B2", "C3", "E5", "F6"):
            assert f"={value}" not in result
        # the empty secret value must be masked too, never left raw
        assert "secret=***" in result
        assert "secret=&" not in result

    def test_case_insensitive_key_match(self) -> None:
        result = redact_query("PASSWORD=hunter2", max_len=100)

        assert "hunter2" not in result
        assert "PASSWORD=***" in result


class TestRedactQueryNormalBehavior:
    """Non-sensitive params pass through; truncation still applies."""

    def test_non_sensitive_params_untouched(self) -> None:
        result = redact_query("page=2&limit=50&q=hello world", max_len=1000)

        assert result == "page=2&limit=50&q=hello world"

    def test_valueless_param_preserved(self) -> None:
        result = redact_query("flag&password=x", max_len=1000)

        assert "flag" in result
        assert "password=***" in result

    def test_long_query_truncated_to_max_len(self) -> None:
        query = "&".join(f"k{i}=value{i}" for i in range(100))

        result = redact_query(query, max_len=_MAX_QUERY_LOG_LEN)

        assert len(result) <= _MAX_QUERY_LOG_LEN

    def test_default_max_len_applied(self) -> None:
        query = "x=" + "a" * 10_000

        result = redact_query(query)

        assert len(result) <= _MAX_QUERY_LOG_LEN
