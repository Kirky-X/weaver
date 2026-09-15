# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Protocol validation utilities for runtime interface checking.

This module provides tools to verify that classes correctly implement
their declared Protocols at runtime.
"""

from __future__ import annotations

import inspect
from typing import Any


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
        if name.startswith("_"):
            continue
        attr = getattr(protocol, name)
        if callable(attr) or isinstance(attr, property):
            # Skip methods that are inherited from Protocol base
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
                # Implementation must accept all Protocol params (may have
                # extra optional ones). *args/**kwargs on the implementation
                # absorb any protocol params.
                obj_params = [p for p in obj_sig.parameters.values() if p.name != "self"]
                named = {p.name for p in obj_params}
                has_var_pos = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in obj_params)
                has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in obj_params)
                for proto_param in proto_sig.parameters.values():
                    if proto_param.name == "self":
                        continue
                    if proto_param.kind is inspect.Parameter.KEYWORD_ONLY:
                        ok = proto_param.name in named or has_var_kw
                    elif proto_param.kind in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    ):
                        ok = True
                    else:
                        ok = proto_param.name in named or has_var_pos
                    if not ok:
                        wrong_signature.append(
                            f"{method_name}: expected param '{proto_param.name}', "
                            f"got {[p.name for p in obj_params]}"
                        )
                        break
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


class ExplicitInterfaceMixin:
    """Mixin that validates Protocol implementation at class definition time.

    Usage:
        class MyService(ExplicitInterfaceMixin, implements=[MyProtocol]):
            ...

        # Or with multiple protocols:
        class MyService(ExplicitInterfaceMixin, implements=[ProtoA, ProtoB]):
            ...

    ``implements`` accepts either a single Protocol class or a list of them;
    the list form is preferred when more than one contract is intended, so
    that the relationship stays explicit.
    """

    def __init_subclass__(cls, implements: type | list[type] | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if implements is None:
            return
        protocols = implements if isinstance(implements, list) else [implements]
        for protocol in protocols:
            assert_implements(cls, protocol)


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

    # Mirror assert_implements: also surface annotation-only members so the
    # two discovery paths cannot drift apart.
    if hasattr(protocol, "__annotations__"):
        for name in protocol.__annotations__:
            if name.startswith("_"):
                continue
            if name not in methods:
                methods.append(name)

    return methods
