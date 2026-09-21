# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Tests for log sensitive-data redaction."""

from core.observability.logging import redact_sensitive_data


class TestCredentialRedaction:
    """bearer/token patterns must redact credentials, not prose."""

    def test_bearer_jwt_redacted(self) -> None:
        msg = "Authorization: bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.sig"
        redacted = redact_sensitive_data(msg)
        assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
        assert "bearer ***REDACTED***" in redacted

    def test_long_token_value_redacted(self) -> None:
        msg = "token ghp_0123456789abcdefghijklmnopqrstuvwxyz"
        redacted = redact_sensitive_data(msg)
        assert "ghp_0123456789abcdefghijklmnopqrstuvwxyz" not in redacted

    def test_token_equals_form_redacted(self) -> None:
        msg = "access_token=ya29.a0AfH6SMBx1234567890123456789"
        redacted = redact_sensitive_data(msg)
        assert "ya29.a0AfH6SMBx1234567890123456789" not in redacted

    def test_prose_not_redacted(self) -> None:
        """Everyday 'token' wording (tokenizer semantics) must survive."""
        assert redact_sensitive_data("token was refreshed for session") == (
            "token was refreshed for session"
        )
        assert redact_sensitive_data("token count exceeded budget") == (
            "token count exceeded budget"
        )
        assert redact_sensitive_data("LLM token usage: 512/2048") == ("LLM token usage: 512/2048")

    def test_short_values_not_redacted(self) -> None:
        assert redact_sensitive_data("token abc") == "token abc"

    def test_password_patterns_still_redacted(self) -> None:
        assert redact_sensitive_data("password=hunter2") == "password=***REDACTED***"

    def test_connection_string_still_redacted(self) -> None:
        msg = "connecting to postgres://admin:secret@db:5432/weaver"
        redacted = redact_sensitive_data(msg)
        assert "secret" not in redacted
