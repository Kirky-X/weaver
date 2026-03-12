"""Base storage repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseRepository(ABC):
    """Abstract base for all repositories."""

    @abstractmethod
    async def get(self, id: Any) -> Any:
        """Get a record by ID."""
        ...

    @abstractmethod
    async def create(self, data: Any) -> Any:
        """Create a new record."""
        ...

    @abstractmethod
    async def update(self, id: Any, data: Any) -> Any:
        """Update an existing record."""
        ...
