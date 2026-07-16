# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base test class for Pydantic View model alignment tests."""

from typing import ClassVar

import pytest
from pydantic import BaseModel


class ViewTestBase:
    """Base class providing common View alignment tests.

    Subclasses MUST define:
        view_class: The Pydantic model class to test
        required_fields: Set of field names that must be present
        removed_fields: Set of field names that must NOT be present
        create_minimal_instance() -> BaseModel: Create a minimal valid instance
    """

    view_class: ClassVar[type[BaseModel]]
    required_fields: ClassVar[set[str]]
    removed_fields: ClassVar[set[str]]

    @staticmethod
    def create_minimal_instance() -> BaseModel:
        """Create a minimal valid instance of the view class. Override in subclass."""
        raise NotImplementedError

    def test_removed_fields_not_present(self):
        field_names = set(self.view_class.model_fields.keys())
        for field in self.removed_fields:
            assert (
                field not in field_names
            ), f"Removed field '{field}' still present in {self.view_class.__name__}"

    def test_required_fields_present(self):
        field_names = set(self.view_class.model_fields.keys())
        for field in self.required_fields:
            assert (
                field in field_names
            ), f"Required field '{field}' missing from {self.view_class.__name__}"

    def test_uses_pydantic_v2_config_dict(self):
        assert self.view_class.model_config.get("from_attributes") is True

    def test_default_values(self):
        """Subclasses should override to test specific defaults."""
        instance = self.create_minimal_instance()
        assert instance is not None

    def test_serialize_to_dict(self):
        instance = self.create_minimal_instance()
        data = instance.model_dump()
        assert isinstance(data, dict)

    def test_removed_fields_not_in_dump(self):
        instance = self.create_minimal_instance()
        data = instance.model_dump()
        for field in self.removed_fields:
            assert field not in data, f"Removed field '{field}' still in model_dump()"
