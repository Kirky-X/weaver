# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""HMAC signing utilities for data integrity verification.

This module provides tools for signing and verifying data using HMAC,
preventing tampering with serialized data files (e.g., index files).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import contextlib
import os
import secrets
from dataclasses import dataclass
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_ALGORITHM = "sha256"
SIGNATURE_KEY_ENV = "INDEX_SIGNING_KEY"
SIGNATURE_FIELD = "__signature__"

# Whitelist of hash algorithms accepted for HMAC signing. A bare
# getattr(hashlib, algorithm) would also accept weak digests (md5, sha1),
# so the lookup goes through this explicit mapping instead.
ALLOWED_ALGORITHMS: dict[str, Any] = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}


# ── Exceptions ─────────────────────────────────────────────────────────────


class IntegrityError(Exception):
    """Raised when data integrity verification fails."""

    pass


# ── Key Management ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SigningKey:
    """HMAC signing key container.

    Attributes:
        key: The raw signing key bytes.
        algorithm: The hash algorithm to use.
    """

    key: bytes
    algorithm: str = DEFAULT_ALGORITHM

    def __post_init__(self) -> None:
        """Reject unknown algorithms early (fail fast on config errors)."""
        if self.algorithm not in ALLOWED_ALGORITHMS:
            raise ValueError(
                f"Unsupported signing algorithm '{self.algorithm}'. "
                f"Allowed: {sorted(ALLOWED_ALGORITHMS)}"
            )

    @classmethod
    def from_env(cls, env_var: str = SIGNATURE_KEY_ENV) -> SigningKey:
        """Create a SigningKey from environment variable.

        Args:
            env_var: Environment variable name.

        Returns:
            SigningKey instance.

        Raises:
            RuntimeError: If the environment variable is not set. A random
                key would invalidate every persisted signature across
                restarts/instances, so a missing key fails fast instead.
                Set the environment variable explicitly.

        """
        key_str = os.environ.get(env_var)

        if key_str:
            return cls(key=key_str.encode("utf-8"))

        raise RuntimeError(
            f"Signing key environment variable '{env_var}' is not set. "
            f"A randomly generated key would invalidate persisted signatures "
            f"on every restart. Set {env_var} (e.g. via "
            f'`python -c "import secrets; print(secrets.token_hex(32))"`).'
        )

    @classmethod
    def generate(cls, length: int = 32) -> SigningKey:
        """Generate a new random signing key.

        Args:
            length: Key length in bytes.

        Returns:
            SigningKey with random key.
        """
        return cls(key=secrets.token_bytes(length))


# ── Signing Functions ─────────────────────────────────────────────────────


def sign_data(data: dict[str, Any], key: SigningKey) -> str:
    """Sign data dictionary using HMAC.

    Args:
        data: Data to sign (will be JSON serialized).
        key: Signing key.

    Returns:
        Hexadecimal signature string.
    """
    # Serialize data deterministically (sorted keys)
    data_bytes = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")

    # Compute HMAC (algorithm is whitelist-validated in SigningKey)
    signature = hmac.new(
        key.key,
        data_bytes,
        ALLOWED_ALGORITHMS[key.algorithm],
    ).hexdigest()

    return signature


def verify_signature(data: dict[str, Any], signature: str, key: SigningKey) -> bool:
    """Verify data signature using HMAC.

    Args:
        data: Data that was signed.
        signature: Expected signature.
        key: Signing key.

    Returns:
        True if signature is valid.
    """
    # A tampered/foreign payload may carry a non-string signature (e.g. an
    # int parsed from JSON); compare_digest would raise TypeError on that.
    if not isinstance(signature, str):
        return False
    expected = sign_data(data, key)
    return hmac.compare_digest(expected, signature)


# ── Signed JSON Operations ────────────────────────────────────────────────


def sign_json(data: dict[str, Any], key: SigningKey) -> dict[str, Any]:
    """Add signature to JSON data.

    Args:
        data: Data to sign.
        key: Signing key.

    Returns:
        Data with added signature field.
    """
    # Create a copy without the signature field if present
    data_to_sign = {k: v for k, v in data.items() if k != SIGNATURE_FIELD}

    signature = sign_data(data_to_sign, key)

    result = dict(data_to_sign)
    result[SIGNATURE_FIELD] = signature
    return result


def verify_json(data: dict[str, Any], key: SigningKey) -> dict[str, Any]:
    """Verify and extract signed JSON data.

    Args:
        data: Signed JSON data.
        key: Signing key.

    Returns:
        Original data without signature field.

    Raises:
        IntegrityError: If signature is missing or invalid.
    """
    if SIGNATURE_FIELD not in data:
        raise IntegrityError("Missing signature field")

    signature = data[SIGNATURE_FIELD]
    data_without_sig = {k: v for k, v in data.items() if k != SIGNATURE_FIELD}

    if not verify_signature(data_without_sig, signature, key):
        raise IntegrityError("Invalid signature - data may have been tampered with")

    return data_without_sig


def load_signed_json(
    file_path: str | os.PathLike[str],
    key: SigningKey,
) -> dict[str, Any]:
    """Load and verify signed JSON file.

    Args:
        file_path: Path to signed JSON file.
        key: Signing key.

    Returns:
        Verified data.

    Raises:
        FileNotFoundError: If file does not exist.
        json.JSONDecodeError: If file is not valid JSON.
        IntegrityError: If signature is missing or invalid.
    """
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    return verify_json(data, key)


def save_signed_json(
    data: dict[str, Any],
    file_path: str | os.PathLike[str],
    key: SigningKey,
) -> None:
    """Save data as signed JSON file.

    Args:
        data: Data to save.
        file_path: Output file path.
        key: Signing key.
    """
    signed_data = sign_json(data, key)

    # Write to a temp file in the same directory, then atomically replace:
    # a crash mid-write must not leave a truncated/invalid signed file.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=os.fspath(os.path.dirname(os.fspath(file_path)) or "."),
            prefix=".signed-",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = f.name
            json.dump(signed_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, file_path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def is_signed_json_file(file_path: str | os.PathLike[str]) -> bool:
    """Check if a file appears to be a signed JSON file.

    Args:
        file_path: Path to check.

    Returns:
        True if file contains __signature__ field.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return SIGNATURE_FIELD in data
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError):
        return False


__all__ = [
    "DEFAULT_ALGORITHM",
    "SIGNATURE_FIELD",
    "SIGNATURE_KEY_ENV",
    "IntegrityError",
    "SigningKey",
    "is_signed_json_file",
    "load_signed_json",
    "save_signed_json",
    "sign_data",
    "sign_json",
    "verify_json",
    "verify_signature",
]
