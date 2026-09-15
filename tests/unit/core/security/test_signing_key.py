# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SigningKey key management.

Regression: ``from_env`` previously fell back to a freshly random
key when the environment variable was missing, silently invalidating every
persisted signature across restarts. It must fail fast with an actionable
message instead.
"""

from __future__ import annotations

import pytest

from core.security.crypto.signing import (
    SIGNATURE_KEY_ENV,
    IntegrityError,
    SigningKey,
    sign_data,
    verify_signature,
)


class TestSigningKeyFromEnvFailFast:
    """A missing signing key must fail loudly, never silently rotate."""

    def test_missing_env_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SIGNATURE_KEY_ENV, raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            SigningKey.from_env()

        # Error must name the exact variable to set (actionable startup error).
        assert SIGNATURE_KEY_ENV in str(exc_info.value)

    def test_error_message_includes_remediation_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SIGNATURE_KEY_ENV, raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            SigningKey.from_env()

        assert "Set" in str(exc_info.value)
        assert "secrets" in str(exc_info.value)

    def test_empty_string_env_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SIGNATURE_KEY_ENV, "")

        with pytest.raises(RuntimeError):
            SigningKey.from_env()

    def test_custom_env_var_name_fail_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            SigningKey.from_env(env_var="MY_CUSTOM_KEY")

        assert "MY_CUSTOM_KEY" in str(exc_info.value)

    def test_set_env_returns_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SIGNATURE_KEY_ENV, "a" * 32)

        key = SigningKey.from_env()

        assert key.key == ("a" * 32).encode("utf-8")


class TestSigningRoundTrip:
    """Sanity: explicit keys keep signing/verifying intact."""

    def test_sign_and_verify_round_trip(self) -> None:
        key = SigningKey.generate()
        data = {"payload": "integrity-check", "n": 42}

        signature = sign_data(data, key)

        assert verify_signature(data, signature, key) is True
        assert verify_signature({"payload": "tampered", "n": 42}, signature, key) is False

    def test_verify_rejects_wrong_key(self) -> None:
        data = {"payload": "x"}

        signature = sign_data(data, SigningKey.generate())

        assert verify_signature(signature=signature, data=data, key=SigningKey.generate()) is False


class TestSigningKeyGenerate:
    """Explicit generation stays available for runtime key creation."""

    def test_generate_random_and_sized(self) -> None:
        key_a = SigningKey.generate()
        key_b = SigningKey.generate()

        assert len(key_a.key) == 32
        assert key_a.key != key_b.key

    def test_generate_custom_length(self) -> None:
        assert len(SigningKey.generate(length=16).key) == 16


class TestSignJsonTamperDetection:
    """Signed JSON containers must reject tampering."""

    def test_tampered_payload_raises_integrity_error(self) -> None:
        from core.security.crypto.signing import sign_json, verify_json

        key = SigningKey.generate()
        signed = sign_json({"role": "user"}, key)
        signed["role"] = "admin"

        with pytest.raises(IntegrityError):
            verify_json(signed, key)


class TestAlgorithmWhitelist:
    """Signing algorithms are restricted to an explicit whitelist."""

    def test_weak_algorithms_rejected(self) -> None:
        for weak in ("md5", "sha1", "new", "__builtins__"):
            with pytest.raises(ValueError, match="Unsupported signing algorithm"):
                SigningKey(key=b"k", algorithm=weak)

    def test_allowed_algorithms_accepted(self) -> None:
        from core.security.crypto.signing import ALLOWED_ALGORITHMS, sign_data

        for algo in ("sha256", "sha384", "sha512"):
            key = SigningKey(key=b"k", algorithm=algo)
            assert sign_data({"a": 1}, key)

    def test_default_algorithm_sha256(self) -> None:
        assert SigningKey.generate().algorithm == "sha256"
