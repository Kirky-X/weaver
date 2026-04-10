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
