# LadybugTemporalRepo Specification

## Overview

LadybugDB compatible temporal graph repository implementation supporting event chain queries and temporal reasoning. Solves the property name mismatch issue in TemporalGraphRepo.

---

## ADDED Requirements

### Requirement: EventNode schema compatibility

The system SHALL use property names that match the LadybugDB schema.

#### Scenario: Property mapping
- **WHEN** querying EventNode
- **THEN** it uses `content` instead of `description`
- **AND** it uses `timestamp` instead of `event_time`
- **AND** it supports the `attributes` JSON field

### Requirement: Get temporal chain

The system SHALL support retrieving event chains ordered by time.

#### Scenario: Retrieve ordered events
- **WHEN** calling `get_temporal_chain(limit=100)`
- **THEN** it returns a list of events ordered by `timestamp` ascending

#### Scenario: Empty chain
- **WHEN** there is no event data
- **THEN** it returns an empty list

### Requirement: Append to chain

The system SHALL support appending events to the temporal chain.

#### Scenario: Append new event
- **WHEN** calling `append_to_chain(event)`
- **THEN** it creates an EventNode and establishes a FOLLOWED_BY relationship

### Requirement: Cypher syntax adaptation

The system SHALL use LadybugDB compatible temporal query syntax.

#### Scenario: DateTime function compatibility
- **WHEN** queries involve time comparisons
- **THEN** it uses INT64 timestamp instead of Neo4j datetime functions

### Requirement: Protocol implementation

The system SHALL implement the same interface as TemporalGraphRepo.

#### Scenario: Drop-in replacement
- **WHEN** using LadybugTemporalRepo as a replacement for TemporalGraphRepo
- **THEN** all public methods behave consistently
