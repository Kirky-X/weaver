# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API schema type definitions.

Provides reusable type definitions for API schemas, including precision-controlled
float types that automatically serialize to 2 decimal places.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import PlainSerializer

# Float that serializes to 2 decimal places
RoundedFloat = Annotated[
    float,
    PlainSerializer(lambda x: round(x, 2), return_type=float),
]

# Optional float that serializes to 2 decimal places (None remains None)
RoundedFloatOpt = Annotated[
    float | None,
    PlainSerializer(lambda x: round(x, 2) if x is not None else None, return_type=float | None),
]
