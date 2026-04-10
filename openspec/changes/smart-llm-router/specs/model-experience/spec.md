## ADDED Requirements

### Requirement: ExperienceStore subscribes to LLMUsageEvent

The ExperienceStore SHALL subscribe to the EventBus for LLMUsageEvent and maintain in-memory counters for each (call_point, provider, model) triplet, tracking call count, success count, failure count, total latency, and last call time.

#### Scenario: Successful call recorded
- **WHEN** a LLMUsageEvent with success=true is published
- **THEN** the corresponding triplet's success_count increments by 1
- **AND** total_latency_ms increases by event.latency_ms

#### Scenario: Failed call recorded
- **WHEN** a LLMUsageEvent with success=false is published
- **THEN** the corresponding triplet's failure_count increments by 1
- **AND** last_error_type is updated to event.error_type

### Requirement: Experience snapshot supports reliability calculation

The ExperienceStore SHALL provide a method to retrieve experience data for a given (call_point, provider, model) triplet, including computed reliability score (success_rate) and average latency.

#### Scenario: Retrieve experience with sufficient data
- **WHEN** experience is requested for a triplet with 100 calls (95 success, 5 failure)
- **THEN** reliability score returned is 0.95
- **AND** avg_latency_ms is total_latency_ms / 100

#### Scenario: Retrieve experience with no data
- **WHEN** experience is requested for a triplet with no recorded calls
- **THEN** reliability score defaults to 1.0 (optimistic for new models)
- **AND** avg_latency_ms defaults to 0.0

### Requirement: ExperienceStore initializes from relational_pool

On startup, the ExperienceStore SHALL load the last 24 hours of aggregated data from `LLMUsageRepo.get_summary()` via the relational_pool to pre-warm experience counters, avoiding cold-start penalties.

#### Scenario: Warm start with historical data
- **WHEN** ExperienceStore starts and relational_pool has data from the last 24 hours
- **THEN** experience counters are populated with aggregated call_count, success_count, and latency data

#### Scenario: Cold start with no historical data
- **WHEN** ExperienceStore starts and relational_pool has no recent data
- **THEN** experience counters are empty
- **AND** reliability defaults to 1.0 for all models (optimistic initialization)

### Requirement: Thompson Sampling beta distribution

The ExperienceStore SHALL maintain Thompson Sampling Beta distribution parameters (alpha, beta) for each triplet, updated on each success or failure, to provide exploration bonuses for less-sampled models.

#### Scenario: New model has high exploration bonus
- **WHEN** a model has fewer samples than warmup_calls threshold (default: 3)
- **THEN** thompson_sample() returns a value with high variance (wide Beta distribution)
- **AND** the model has a reasonable chance of ranking higher despite no track record

#### Scenario: Mature model has narrow distribution
- **WHEN** a model has 500+ calls with 98% success rate
- **THEN** thompson_sample() returns values tightly clustered around 0.98
- **AND** exploration bonus is minimal

### Requirement: Experience data expiry

Experience counters SHALL automatically decay older data, with records older than 24 hours weighted at 50% and records older than 7 days excluded from scoring calculations.

#### Scenario: Old data weighted down
- **WHEN** scoring a model with calls from both today and 3 days ago
- **THEN** today's calls contribute full weight
- **AND** 3-day-old calls contribute 50% weight
