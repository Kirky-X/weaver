# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

"""Data models for deduplication operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TitleItem:
    """Item with title for SimHash deduplication."""

    url: str
    title: str
    simhash: int | None = None
    created_at: float | None = None
