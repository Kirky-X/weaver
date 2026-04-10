# LadybugEntityRepo Specification

## Overview

LadybugDB compatible entity repository implementation supporting entity relationship query operations. Solves the issue where Neo4jEntityRepo uses Neo4j-specific Cypher syntax (`type(r)`) that is not available on LadybugDB.

---

## ADDED Requirements

### Requirement: Get relation types for entity

The system SHALL support querying all relation types for an entity using LadybugDB compatible syntax.

#### Scenario: Query relation types successfully
- **WHEN** calling `get_relation_types("阿里巴巴", "组织机构")`
- **THEN** it returns a list of all relation types for the entity, including `relation_type`, `target_count`, `primary_direction`

#### Scenario: Entity not found
- **WHEN** the entity does not exist
- **THEN** it returns an empty list

### Requirement: Find entities by relation types

The system SHALL support searching for related entities by relation types.

#### Scenario: Search with specific relation types
- **WHEN** calling `find_by_relation_types("阿里巴巴", "组织机构", ["投资", "合作"], 50)`
- **THEN** it returns entities matching the relations

#### Scenario: Search without relation type filter
- **WHEN** no relation types are specified
- **THEN** it returns all related entities

### Requirement: Cypher syntax compatibility

The system SHALL use LadybugDB compatible Cypher syntax.

#### Scenario: Relation type access
- **WHEN** querying relation types
- **THEN** it uses `r.edge_type` instead of `type(r)`

#### Scenario: Node property access
- **WHEN** accessing node properties
- **THEN** it uses property names supported by LadybugDB

### Requirement: Protocol implementation

The system SHALL implement the EntityRepository Protocol.

#### Scenario: Interface compliance
- **WHEN** instantiating LadybugEntityRepo
- **THEN** it satisfies all method signatures of the EntityRepository Protocol
