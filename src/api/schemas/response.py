# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified API response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper.

    Attributes:
        code: Response code (0 for success).
        message: Response message.
        data: Response payload.
        timestamp: Response timestamp.
    """

    code: int = Field(default=0, description="Response code, 0 for success")
    message: str = Field(default="success", description="Response message")
    data: T | None = Field(default=None, description="Response payload")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Response timestamp",
    )


class ErrorResponse(BaseModel):
    """Error response schema.

    Attributes:
        code: Error code.
        message: Error message.
        details: Optional error details.
    """

    code: int = Field(description="Error code")
    message: str = Field(description="Error message")
    details: dict[str, Any] | None = Field(default=None, description="Optional error details")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response schema.

    Attributes:
        items: List of items.
        total: Total number of items.
        page: Current page number.
        page_size: Number of items per page.
        total_pages: Total number of pages.
    """

    items: list[T] = Field(default_factory=list, description="List of items")
    total: int = Field(default=0, description="Total number of items")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=20, description="Number of items per page")
    total_pages: int = Field(default=0, description="Total number of pages")

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[T]:
        """Create a paginated response.

        Args:
            items: List of items.
            total: Total number of items.
            page: Current page number.
            page_size: Number of items per page.

        Returns:
            PaginatedResponse instance.
        """
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
