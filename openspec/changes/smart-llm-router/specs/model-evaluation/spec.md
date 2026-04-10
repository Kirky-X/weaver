## ADDED Requirements

### Requirement: Shadow evaluation triggers on sampled requests

When shadow evaluation is enabled, the system SHALL randomly sample a configurable percentage of LLM requests and issue parallel shadow calls to candidate models without blocking or delaying the main response.

#### Scenario: Shadow call triggered by sample rate
- **WHEN** eval is enabled with sample_rate = 0.1 and a request is made
- **THEN** there is a 10% probability of a shadow call being issued
- **AND** the shadow call does not affect the main call's response time

#### Scenario: Shadow call uses different model
- **WHEN** a shadow call is triggered for call_point="classifier"
- **THEN** the shadow call routes to the configured candidate model (not the primary)
- **AND** the same prompt payload is sent to both models

### Requirement: Shadow call results recorded via event bus

Each shadow call completion SHALL publish an LLMCompareEvent to the EventBus containing the call_point, primary_model, candidate_model, primary_latency, candidate_latency, primary_output, candidate_output, and success status for both.

#### Scenario: Shadow call completes successfully
- **WHEN** a shadow call completes
- **THEN** an LLMCompareEvent is published with both models' results
- **AND** the event contains latency and output for comparison

#### Scenario: Shadow call fails
- **WHEN** a shadow call fails with an error
- **THEN** an LLMCompareEvent is published with the failure details
- **AND** the candidate model's success flag is false
- **AND** the main call's result is unaffected

### Requirement: Comparison results aggregated to relational_pool

LLMCompareEvent handlers SHALL buffer comparison results to Redis (following the LLMUsageBuffer pattern) and periodically aggregate to relational_pool using upsert operations.

#### Scenario: Comparison results persisted
- **WHEN** LLMCompareEvent handlers process events
- **THEN** results are buffered to Redis with TTL
- **AND** aggregated records are upserted to relational_pool via the RelationalPool protocol

#### Scenario: Redis unavailable
- **WHEN** Redis is not available
- **THEN** comparison events are logged but not buffered
- **AND** the main call path is not affected

### Requirement: Comparison query API

The system SHALL provide a query method to retrieve aggregated comparison statistics between two models for a given call_point and time range, including win rate, average latency difference, and output quality metrics.

#### Scenario: Query comparison statistics
- **WHEN** comparison stats are queried for classifier between model-A and model-B over the last 7 days
- **THEN** the result includes: model-A win count, model-B win count, avg latency delta
- **AND** results are grouped by call_point

### Requirement: EvalRunner isolation from main path

The EvalRunner SHALL operate entirely asynchronously and independently from the main LLM call path. Any failure in EvalRunner SHALL NOT propagate to or delay the main call.

#### Scenario: EvalRunner error isolation
- **WHEN** EvalRunner encounters an error during shadow call setup
- **THEN** the error is logged
- **AND** the main call has already returned its result
- **AND** no exception is raised to the caller
