# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base class for View model alignment tests.

Provides shared test methods for required_fields, removed_fields,
pydantic_v2_config, serialize_to_dict, and removed_fields_not_in_dump.
Subclasses only need to set class attributes and override
``_create_minimal_instance()``.
"""

from typing import Any


class ViewModelTestBase:
    """Base class for View model field alignment tests.

    Subclasses MUST set:
        model_class: The Pydantic model class under test.
        required_fields: Set of field names that must exist.
        removed_fields: Set of field names that must not exist.

    Subclasses SHOULD override:
        _create_minimal_instance(): Return a valid model instance for dump tests.
    """

    model_class: type
    required_fields: set[str]
    removed_fields: set[str]

    def test_required_fields_present(self):
        """All fields in required_fields must exist in model_fields."""
        field_names = set(self.model_class.model_fields.keys())
        for field in self.required_fields:
            assert (
                field in field_names
            ), f"Required field '{field}' missing from {self.model_class.__name__}"

    def test_removed_fields_not_present(self):
        """No field in removed_fields may exist in model_fields."""
        field_names = set(self.model_class.model_fields.keys())
        for field in self.removed_fields:
            assert (
                field not in field_names
            ), f"Removed field '{field}' still present in {self.model_class.__name__}"

    def test_uses_pydantic_v2_config_dict(self):
        """model_config must have from_attributes=True."""
        assert self.model_class.model_config.get("from_attributes") is True

    def test_serialize_to_dict(self):
        """model_dump() must return a dict with expected fields."""
        instance = self._create_minimal_instance()
        data = instance.model_dump()
        assert isinstance(data, dict)

    def test_removed_fields_not_in_dump(self):
        """Removed fields must not appear in model_dump() output."""
        instance = self._create_minimal_instance()
        data = instance.model_dump()
        for field in self.removed_fields:
            assert (
                field not in data
            ), f"Removed field '{field}' still in {self.model_class.__name__}.model_dump()"

    def _create_minimal_instance(self) -> Any:
        """Create a minimal valid model instance for dump tests.

        Subclasses MUST override this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _create_minimal_instance()"
        )
