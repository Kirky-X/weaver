# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.migration.mapping_registry module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.migration.exceptions import MigrationError
from modules.migration.mapping_registry import (
    MappingRegistry,
    NodeMapping,
    PropertyMapping,
    RelMapping,
    create_example_mapping_file,
)


class TestPropertyMapping:
    """Test PropertyMapping dataclass."""

    def test_create_property_mapping(self):
        """Test creating PropertyMapping."""
        mapping = PropertyMapping(
            source="old_name",
            target="new_name",
        )

        assert mapping.source == "old_name"
        assert mapping.target == "new_name"
        assert mapping.default is None
        assert mapping.transform is None

    def test_property_mapping_with_default(self):
        """Test PropertyMapping with default."""
        mapping = PropertyMapping(
            source="status",
            target="state",
            default="active",
        )

        assert mapping.default == "active"


class TestNodeMapping:
    """Test NodeMapping dataclass."""

    def test_create_node_mapping(self):
        """Test creating NodeMapping."""
        mapping = NodeMapping(
            source_label="Person",
            target_label="Entity",
        )

        assert mapping.source_label == "Person"
        assert mapping.target_label == "Entity"
        assert mapping.property_mappings == []
        assert mapping.default_values == {}

    def test_node_mapping_with_properties(self):
        """Test NodeMapping with property mappings."""
        mapping = NodeMapping(
            source_label="Person",
            target_label="Entity",
            property_mappings=[
                PropertyMapping(source="name", target="canonical_name"),
            ],
            default_values={"tier": 3},
        )

        assert len(mapping.property_mappings) == 1
        assert mapping.default_values["tier"] == 3


class TestRelMapping:
    """Test RelMapping dataclass."""

    def test_create_rel_mapping(self):
        """Test creating RelMapping."""
        mapping = RelMapping(
            source_type="KNOWS",
            target_type="RELATED_TO",
        )

        assert mapping.source_type == "KNOWS"
        assert mapping.target_type == "RELATED_TO"

    def test_rel_mapping_with_properties(self):
        """Test RelMapping with property mappings."""
        mapping = RelMapping(
            source_type="WORKS_AT",
            target_type="AFFILIATED_WITH",
            property_mappings=[
                PropertyMapping(source="role", target="position"),
            ],
        )

        assert len(mapping.property_mappings) == 1


class TestMappingRegistry:
    """Test MappingRegistry class."""

    def test_init(self):
        """Test initialization."""
        registry = MappingRegistry()

        assert registry._node_mappings == {}
        assert registry._rel_mappings == {}

    def test_has_node_mapping_false(self):
        """Test has_node_mapping returns False for missing mapping."""
        registry = MappingRegistry()

        assert registry.has_node_mapping("NonExistent") is False

    def test_has_rel_mapping_false(self):
        """Test has_rel_mapping returns False for missing mapping."""
        registry = MappingRegistry()

        assert registry.has_rel_mapping("NonExistent") is False

    def test_list_node_mappings_empty(self):
        """Test list_node_mappings when empty."""
        registry = MappingRegistry()

        assert registry.list_node_mappings() == []

    def test_list_rel_mappings_empty(self):
        """Test list_rel_mappings when empty."""
        registry = MappingRegistry()

        assert registry.list_rel_mappings() == []

    def test_clear(self):
        """Test clear method."""
        registry = MappingRegistry()
        registry._node_mappings["test"] = MagicMock()
        registry._rel_mappings["test"] = MagicMock()

        registry.clear()

        assert registry._node_mappings == {}
        assert registry._rel_mappings == {}

    def test_transform_node_no_mapping(self):
        """Test transform_node when no mapping exists."""
        registry = MappingRegistry()

        label, props = registry.transform_node("Person", {"name": "John"})

        assert label == "Person"
        assert props == {"name": "John"}

    def test_transform_rel_no_mapping(self):
        """Test transform_rel when no mapping exists."""
        registry = MappingRegistry()

        rel_type, props = registry.transform_rel("KNOWS", {"since": 2020})

        assert rel_type == "KNOWS"
        assert props == {"since": 2020}


class TestMappingRegistryLoad:
    """Test MappingRegistry.load method."""

    def test_load_missing_file(self, tmp_path):
        """Test load with missing file."""
        registry = MappingRegistry()

        with pytest.raises(MigrationError, match="Mapping file not found"):
            registry.load(str(tmp_path / "nonexistent.yaml"))

    def test_load_empty_file(self, tmp_path):
        """Test load with empty file."""
        registry = MappingRegistry()
        mapping_file = tmp_path / "empty.yaml"
        mapping_file.write_text("")

        registry.load(str(mapping_file))

        assert registry.list_node_mappings() == []
        assert registry.list_rel_mappings() == []

    def test_load_valid_yaml(self, tmp_path):
        """Test load with valid YAML."""
        registry = MappingRegistry()
        mapping_file = tmp_path / "mappings.yaml"
        mapping_file.write_text("""
nodes:
  - source_label: Person
    target_label: Entity
    property_mapping:
      - name: canonical_name
relations:
  - source_type: KNOWS
    target_type: RELATED_TO
""")

        registry.load(str(mapping_file))

        assert "Person" in registry.list_node_mappings()
        assert "KNOWS" in registry.list_rel_mappings()

    def test_load_invalid_yaml(self, tmp_path):
        """Test load with invalid YAML."""
        registry = MappingRegistry()
        mapping_file = tmp_path / "invalid.yaml"
        mapping_file.write_text("invalid: [yaml: content")

        with pytest.raises(MigrationError, match="Invalid YAML"):
            registry.load(str(mapping_file))


class TestMappingRegistryTransform:
    """Test MappingRegistry transform methods."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Create registry with mappings loaded."""
        registry = MappingRegistry()
        mapping_file = tmp_path / "mappings.yaml"
        mapping_file.write_text("""
nodes:
  - source_label: Person
    target_label: Entity
    key_mapping:
      source_key: name
      target_key: canonical_name
    property_mapping:
      - name: canonical_name
      - person_type: type
    default_values:
      tier: 3
relations:
  - source_type: KNOWS
    target_type: RELATED_TO
    property_mapping:
      - since: established_at
    default_values:
      edge_type: social
""")
        registry.load(str(mapping_file))
        return registry

    def test_transform_node_with_mapping(self, registry):
        """Test transform_node with mapping."""
        label, props = registry.transform_node(
            "Person",
            {"name": "John", "person_type": "individual"},
        )

        assert label == "Entity"
        assert props["canonical_name"] == "John"
        assert props["type"] == "individual"
        assert props["tier"] == 3  # default

    def test_transform_node_missing_property(self, registry):
        """Test transform_node with missing property uses default."""
        label, props = registry.transform_node(
            "Person",
            {"name": "John"},
        )

        assert label == "Entity"
        assert props["canonical_name"] == "John"
        assert props["tier"] == 3

    def test_transform_rel_with_mapping(self, registry):
        """Test transform_rel with mapping."""
        rel_type, props = registry.transform_rel(
            "KNOWS",
            {"since": 2020},
        )

        assert rel_type == "RELATED_TO"
        assert props["established_at"] == 2020
        assert props["edge_type"] == "social"  # default

    def test_has_node_mapping_true(self, registry):
        """Test has_node_mapping returns True for existing mapping."""
        assert registry.has_node_mapping("Person") is True

    def test_has_rel_mapping_true(self, registry):
        """Test has_rel_mapping returns True for existing mapping."""
        assert registry.has_rel_mapping("KNOWS") is True

    def test_list_node_mappings(self, registry):
        """Test list_node_mappings."""
        mappings = registry.list_node_mappings()

        assert "Person" in mappings

    def test_list_rel_mappings(self, registry):
        """Test list_rel_mappings."""
        mappings = registry.list_rel_mappings()

        assert "KNOWS" in mappings


class TestCreateExampleMappingFile:
    """Test create_example_mapping_file function."""

    def test_create_file(self, tmp_path):
        """Test creating example mapping file."""
        file_path = str(tmp_path / "example.yaml")

        create_example_mapping_file(file_path)

        assert Path(file_path).exists()
        content = Path(file_path).read_text()
        assert "nodes:" in content
        assert "relations:" in content

    def test_create_file_creates_parent_dirs(self, tmp_path):
        """Test creating file in non-existent directory."""
        file_path = str(tmp_path / "subdir" / "nested" / "example.yaml")

        create_example_mapping_file(file_path)

        assert Path(file_path).exists()
