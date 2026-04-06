# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Mapping registry for custom migration rules.

Supports YAML-based mapping rules for:
- Node label transformations
- Relationship type transformations
- Property mappings with defaults
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import MigrationError


@dataclass
class PropertyMapping:
    """Property mapping rule.

    Attributes:
        source: Source property name.
        target: Target property name.
        default: Default value if source is missing.
        transform: Transformation function name (optional).
    """

    source: str
    target: str
    default: Any = None
    transform: str | None = None


@dataclass
class NodeMapping:
    """Node label mapping rule.

    Attributes:
        source_label: Source node label.
        target_label: Target node label.
        key_mapping: Mapping for primary key property.
        property_mappings: List of property mappings.
        default_values: Default values for missing properties.
    """

    source_label: str
    target_label: str
    key_mapping: dict[str, str] = field(default_factory=dict)
    property_mappings: list[PropertyMapping] = field(default_factory=list)
    default_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelMapping:
    """Relationship type mapping rule.

    Attributes:
        source_type: Source relationship type.
        target_type: Target relationship type.
        property_mappings: List of property mappings.
        default_values: Default values for missing properties.
    """

    source_type: str
    target_type: str
    property_mappings: list[PropertyMapping] = field(default_factory=list)
    default_values: dict[str, Any] = field(default_factory=dict)


class MappingRegistry:
    """Registry for custom migration mapping rules.

    Supports loading from YAML files and applying transformations
    to nodes and relationships during migration.
    """

    def __init__(self) -> None:
        self._node_mappings: dict[str, NodeMapping] = {}
        self._rel_mappings: dict[str, RelMapping] = {}

    def load(self, path: str) -> None:
        """Load mapping rules from a YAML file.

        Args:
            path: Path to the YAML mapping file.

        Raises:
            MigrationError: If the file cannot be loaded or parsed.
        """
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            raise MigrationError(f"Mapping file not found: {path}")
        except yaml.YAMLError as exc:
            raise MigrationError(f"Invalid YAML in mapping file: {exc}")

        if not data:
            return

        # Parse node mappings
        for node_data in data.get("nodes", []):
            mapping = self._parse_node_mapping(node_data)
            self._node_mappings[mapping.source_label] = mapping

        # Parse relationship mappings
        for rel_data in data.get("relations", []):
            mapping = self._parse_rel_mapping(rel_data)
            self._rel_mappings[mapping.source_type] = mapping

    def _parse_node_mapping(self, data: dict[str, Any]) -> NodeMapping:
        """Parse a node mapping from YAML data."""
        property_mappings = []
        for prop_data in data.get("property_mapping", []):
            if isinstance(prop_data, dict):
                for src, tgt in prop_data.items():
                    property_mappings.append(PropertyMapping(source=src, target=tgt))
            elif isinstance(prop_data, str) and ":" in prop_data:
                src, tgt = prop_data.split(":", 1)
                property_mappings.append(PropertyMapping(source=src.strip(), target=tgt.strip()))

        return NodeMapping(
            source_label=data["source_label"],
            target_label=data["target_label"],
            key_mapping=data.get("key_mapping", {}),
            property_mappings=property_mappings,
            default_values=data.get("default_values", {}),
        )

    def _parse_rel_mapping(self, data: dict[str, Any]) -> RelMapping:
        """Parse a relationship mapping from YAML data."""
        property_mappings = []
        for prop_data in data.get("property_mapping", []):
            if isinstance(prop_data, dict):
                for src, tgt in prop_data.items():
                    property_mappings.append(PropertyMapping(source=src, target=tgt))
            elif isinstance(prop_data, str) and ":" in prop_data:
                src, tgt = prop_data.split(":", 1)
                property_mappings.append(PropertyMapping(source=src.strip(), target=tgt.strip()))

        return RelMapping(
            source_type=data["source_type"],
            target_type=data["target_type"],
            property_mappings=property_mappings,
            default_values=data.get("default_values", {}),
        )

    def transform_node(self, source_label: str, node: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Transform a node using registered mapping rules.

        Args:
            source_label: Source node label.
            node: Node properties.

        Returns:
            Tuple of (target_label, transformed_properties).
        """
        mapping = self._node_mappings.get(source_label)
        if not mapping:
            return source_label, node

        target_props: dict[str, Any] = {}

        # Apply property mappings
        for prop_mapping in mapping.property_mappings:
            value = node.get(prop_mapping.source, prop_mapping.default)
            if value is not None:
                target_props[prop_mapping.target] = value

        # Apply default values
        for key, default in mapping.default_values.items():
            if key not in target_props:
                target_props[key] = default

        # Copy unmapped properties
        for key, value in node.items():
            mapped = False
            for pm in mapping.property_mappings:
                if pm.source == key:
                    mapped = True
                    break
            if not mapped and key not in target_props:
                target_props[key] = value

        return mapping.target_label, target_props

    def transform_rel(self, source_type: str, rel: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Transform a relationship using registered mapping rules.

        Args:
            source_type: Source relationship type.
            rel: Relationship properties.

        Returns:
            Tuple of (target_type, transformed_properties).
        """
        mapping = self._rel_mappings.get(source_type)
        if not mapping:
            return source_type, rel

        target_props: dict[str, Any] = {}

        # Apply property mappings
        for prop_mapping in mapping.property_mappings:
            value = rel.get(prop_mapping.source, prop_mapping.default)
            if value is not None:
                target_props[prop_mapping.target] = value

        # Apply default values
        for key, default in mapping.default_values.items():
            if key not in target_props:
                target_props[key] = default

        # Copy unmapped properties
        for key, value in rel.items():
            mapped = False
            for pm in mapping.property_mappings:
                if pm.source == key:
                    mapped = True
                    break
            if not mapped and key not in target_props:
                target_props[key] = value

        return mapping.target_type, target_props

    def has_node_mapping(self, source_label: str) -> bool:
        """Check if a node mapping exists."""
        return source_label in self._node_mappings

    def has_rel_mapping(self, source_type: str) -> bool:
        """Check if a relationship mapping exists."""
        return source_type in self._rel_mappings

    def list_node_mappings(self) -> list[str]:
        """List all registered source node labels."""
        return list(self._node_mappings.keys())

    def list_rel_mappings(self) -> list[str]:
        """List all registered source relationship types."""
        return list(self._rel_mappings.keys())

    def clear(self) -> None:
        """Clear all registered mappings."""
        self._node_mappings.clear()
        self._rel_mappings.clear()


def create_example_mapping_file(path: str) -> None:
    """Create an example mapping file.

    Args:
        path: Path where to create the example file.
    """
    example = """# Migration Mapping Rules Example
# This file defines custom transformations for database migration

nodes:
  - source_label: "Person"
    target_label: "Entity"
    key_mapping:
      source_key: "name"
      target_key: "canonical_name"
    property_mapping:
      - name: canonical_name
      - person_type: type
      - bio: description
    default_values:
      tier: 3

  - source_label: "Organization"
    target_label: "Entity"
    property_mapping:
      - org_name: canonical_name
      - industry: category
    default_values:
      tier: 2
      type: "organization"

relations:
  - source_type: "KNOWS"
    target_type: "RELATED_TO"
    property_mapping:
      - since: properties
    default_values:
      edge_type: "social"

  - source_type: "WORKS_AT"
    target_type: "AFFILIATED_WITH"
    property_mapping:
      - role: position
    default_values:
      edge_type: "professional"
"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(example)
