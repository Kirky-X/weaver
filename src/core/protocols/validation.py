# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Protocol validation utilities for runtime interface checking.

This module provides tools to verify that classes correctly implement
their declared Protocols at runtime.
"""

from __future__ import annotations

import inspect
from typing import Any, Protocol


def assert_implements(obj: Any, protocol: type) -> None:
    """Assert that obj implements the given protocol.

    This function performs runtime validation that an object implements
    all required methods of a Protocol with compatible signatures.

    Args:
        obj: The object to validate.
        protocol: The Protocol class to check against.

    Raises:
        TypeError: If obj does not implement all required methods.
        ValueError: If protocol is not a Protocol class.

    Example:
        >>> from core.protocols import RelationalPool, assert_implements
        >>> pool = PostgresPool()
        >>> assert_implements(pool, RelationalPool)  # No error if valid
    """
    if not isinstance(protocol, type):
        raise ValueError(f"Expected a Protocol class, got {type(protocol)}")

    # Check if it's a Protocol by checking for _is_protocol attribute
    if not getattr(protocol, "_is_protocol", False):
        raise ValueError(f"{protocol.__name__} is not a Protocol class")

    # Get all methods defined in the Protocol (excluding dunder and inherited)
    protocol_methods: dict[str, Any] = {}
    for name in dir(protocol):
        if name.startswith("_") and name != "__init__":
            continue
        attr = getattr(protocol, name)
        if callable(attr) or isinstance(attr, property):
            # Skip methods that are inherited from Protocol base
            if name in ("startup", "shutdown") and hasattr(Protocol, name):
                continue
            protocol_methods[name] = attr

    # Also check __annotations__ for abstract methods
    if hasattr(protocol, "__annotations__"):
        for name in protocol.__annotations__:
            if name.startswith("_"):
                continue
            if not hasattr(obj, name):
                protocol_methods[name] = None

    missing: list[str] = []
    wrong_signature: list[str] = []

    for method_name in protocol_methods:
        if not hasattr(obj, method_name):
            missing.append(method_name)
            continue

        obj_method = getattr(obj, method_name)
        proto_method = protocol_methods[method_name]

        # Skip property checks
        if isinstance(proto_method, property) or isinstance(obj_method, property):
            continue

        # Skip if proto_method is just ... (Ellipsis placeholder)
        if proto_method is not None and callable(proto_method):
            try:
                obj_sig = inspect.signature(obj_method)
                proto_sig = inspect.signature(proto_method)
                # Compare parameter names (skip 'self')
                obj_params = [p for p in obj_sig.parameters if p != "self"]
                proto_params = [p for p in proto_sig.parameters if p != "self"]
                if obj_params != proto_params:
                    wrong_signature.append(
                        f"{method_name}: expected params {proto_params}, got {obj_params}"
                    )
            except (ValueError, TypeError):
                # Some callables don't have signatures, skip check
                pass

    if missing or wrong_signature:
        error_parts = [f"{obj.__class__.__name__} does not implement {protocol.__name__}:"]
        if missing:
            error_parts.append(f"  Missing methods: {', '.join(missing)}")
        if wrong_signature:
            error_parts.extend([f"  {sig}" for sig in wrong_signature])
        raise TypeError("\n".join(error_parts))


def get_protocol_methods(protocol: type) -> list[str]:
    """Get list of method names required by a Protocol.

    Args:
        protocol: The Protocol class to inspect.

    Returns:
        List of method names that must be implemented.
    """
    if not getattr(protocol, "_is_protocol", False):
        raise ValueError(f"{protocol.__name__} is not a Protocol class")

    methods: list[str] = []
    for name in dir(protocol):
        if name.startswith("_"):
            continue
        attr = getattr(protocol, name)
        if callable(attr) or isinstance(attr, property):
            methods.append(name)

    return methods
