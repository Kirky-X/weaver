# Copyright (c) 2026 KirkyX. All Rights Reserved
"""HMAC signing utilities for data integrity verification.

This module provides tools for signing and verifying data using HMAC,
preventing tampering with serialized data files (e.g., index files).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_ALGORITHM = "sha256"
SIGNATURE_KEY_ENV = "INDEX_SIGNING_KEY"
SIGNATURE_FIELD = "__signature__"


# ── Exceptions ─────────────────────────────────────────────────────────────


class IntegrityError(Exception):
    """Raised when data integrity verification fails."""

    pass


class SigningKeyError(Exception):
    """Raised when signing key is missing or invalid."""

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

    @classmethod
    def from_env(cls, env_var: str = SIGNATURE_KEY_ENV) -> SigningKey:
        """Create a SigningKey from environment variable.

        Args:
            env_var: Environment variable name.

        Returns:
            SigningKey instance.

        Raises:
            SigningKeyError: If key is not set and not in development mode.
        """
        key_str = os.environ.get(env_var)

        if key_str:
            return cls(key=key_str.encode("utf-8"))

        # Generate a random key for development
        generated_key = secrets.token_hex(32)
        logger.warning(
            "signing_key_not_configured",
            env_var=env_var,
            message="Using generated signing key for development. "
            f"Set {env_var} environment variable for production.",
        )
        return cls(key=generated_key.encode("utf-8"))

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

    # Compute HMAC
    signature = hmac.new(
        key.key,
        data_bytes,
        getattr(hashlib, key.algorithm),
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

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(signed_data, f, ensure_ascii=False, indent=2)


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
    "SigningKeyError",
    "is_signed_json_file",
    "load_signed_json",
    "save_signed_json",
    "sign_data",
    "sign_json",
    "verify_json",
    "verify_signature",
]
