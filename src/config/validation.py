# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Deep configuration validation that fails fast at startup.

Structural reference checks (label resolution, placeholder detection) run
here so a misconfigured deployment surfaces one actionable error instead of
confusing per-request routing failures.
"""

from __future__ import annotations

from typing import Any

from core.observability import get_logger

log = get_logger(__name__)

# Values that indicate an unedited template entry
_PLACEHOLDER_VALUES = frozenset({"", "changeme", "placeholder"})
_PLACEHOLDER_PREFIXES = ("your_",)


class ConfigReferenceError(ValueError):
    """Raised when configuration references cannot be resolved at startup."""


def _is_placeholder(label: str) -> bool:
    stripped = label.strip()
    if stripped.lower() in _PLACEHOLDER_VALUES:
        return True
    return any(stripped.lower().startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


def validate_llm_references(settings: Any) -> list[str]:
    """Validate that every call-point label resolves against configured providers.

    A label has the shape ``{type}.{provider}.{model_id}``; it resolves only
    when the provider exists and defines a model entry for that type.

    Args:
        settings: Application settings with an ``llm`` section.

    Returns:
        Soft warnings (e.g. label/model_id mismatches) that do not block startup.

    Raises:
        ConfigReferenceError: With every hard problem and its config section
            path, when any label is unresolvable or a placeholder.
    """
    llm = getattr(settings, "llm", None)
    if llm is None:
        return []
    call_points = getattr(llm, "call_points", None)
    providers = getattr(llm, "providers", None)
    # Non-dict config (partial/mock settings objects) is not validated
    if not isinstance(call_points, dict) or not isinstance(providers, dict):
        return []

    hard: list[str] = []
    soft: list[str] = []

    for cp_name, routing in call_points.items():
        entries = [("primary", getattr(routing, "primary", ""))]
        entries += [
            (f"fallbacks[{i}]", fallback)
            for i, fallback in enumerate(getattr(routing, "fallbacks", None) or [])
        ]
        for field, label in entries:
            section = f"[call-points.{cp_name}].{field}"
            if _is_placeholder(label):
                hard.append(f"{section}: placeholder or empty label '{label}'")
                continue
            parts = label.split(".", 2)
            if len(parts) != 3:
                hard.append(f"{section}: malformed label '{label}' (expected type.provider.model)")
                continue
            llm_type, provider_name, model_id = parts
            provider = providers.get(provider_name)
            if provider is None:
                hard.append(
                    f"{section}: label '{label}' references undefined provider "
                    f"'{provider_name}' (defined: {sorted(providers) or 'none'})"
                )
                continue
            models = getattr(provider, "models", None) or {}
            model_cfg = models.get(llm_type) if isinstance(models, dict) else None
            if model_cfg is None:
                hard.append(
                    f"{section}: label '{label}' needs "
                    f"[providers.{provider_name}.models.{llm_type}] which is not configured"
                )
                continue
            configured_id = (getattr(model_cfg, "model_id", "") or "").strip()
            if configured_id and model_id != configured_id:
                soft.append(
                    f"{section}: label model '{model_id}' does not match configured "
                    f"model_id '{configured_id}'"
                )

    if hard:
        raise ConfigReferenceError(
            "LLM configuration references failed to resolve:\n"
            + "\n".join(f"- {problem}" for problem in hard)
        )
    return soft
