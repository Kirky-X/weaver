# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Input truncation utilities for LLM calls."""

# Input limits per call point (in characters)
INPUT_LIMITS: dict[str, int] = {
    "classifier": 600,
    "categorizer": 1100,
    "quality_scorer": 1500,
    "credibility_checker": 2000,
    "analyze": 3000,
    "summary": 2000,
    "entity_extractor": 2000,
    "default": 2000,
}


def truncate_input(call_point: str, body: str, title: str | None = None) -> str:
    """Truncate input body based on call point limits.

    Args:
        call_point: The call point identifier.
        body: The full body text to truncate.
        title: Optional title to prepend.

    Returns:
        Truncated text with title (if provided) + truncated body.
    """
    limit = INPUT_LIMITS.get(call_point, INPUT_LIMITS["default"])

    if title:
        truncated = f"标题：{title}\n\n正文：{body[:limit]}"
    else:
        truncated = body[:limit]

    return truncated
