## ADDED Requirements

### Requirement: Model selector scores candidates using weighted dimensions

The system SHALL score each candidate model using four weighted dimensions: editorial (preset priority from TOML configuration order), reliability (historical success rate), cost (estimated token cost), and latency (historical P50 response time). A candidate's total score SHALL be the weighted sum of these normalized dimension scores.

#### Scenario: Score calculation with default weights
- **WHEN** three candidate models are evaluated with default auto mode weights
- **THEN** total = editorial × 0.35 + reliability × 0.25 + cost × 0.15 + latency × 0.10
- **AND** each dimension score is normalized to [0.0, 1.0]

#### Scenario: Dimension normalization
- **WHEN** candidate costs range from $0.001 to $0.05
- **THEN** the cheapest candidate receives cost_score = 1.0 and the most expensive receives cost_score = 0.0

### Requirement: Routing modes adjust scoring weights

The system SHALL support three routing modes (auto, fast, best), each with different default weight configurations that shift the scoring preference.

#### Scenario: Fast mode prioritizes cost
- **WHEN** mode is set to "fast"
- **THEN** cost weight is highest (0.30), reliability weight is lowest (0.15)
- **AND** the cheapest viable model ranks higher

#### Scenario: Best mode prioritizes reliability
- **WHEN** mode is set to "best"
- **THEN** reliability weight is highest (0.40), cost weight is lowest (0.05)
- **AND** the most reliable model ranks higher

#### Scenario: Auto mode balances all dimensions
- **WHEN** mode is set to "auto"
- **THEN** editorial weight is highest (0.35), followed by reliability (0.25)
- **AND** cost and latency have lower weights (0.15 and 0.10)

### Requirement: Selector returns sorted fallback chain

The model selector SHALL return a sorted list of candidate labels, with the highest-scoring model as primary and remaining models ordered by score as fallback options.

#### Scenario: All candidates scored
- **WHEN** four candidates are evaluated
- **THEN** the selector returns all four labels sorted by total score descending
- **AND** the first label is the highest-scoring model

#### Scenario: Infeasible selection
- **WHEN** no candidates pass the capability filter (e.g., all require tool calling but none support it)
- **THEN** the selector raises RoutingInfeasibleError with missing capability details

### Requirement: Capability filtering excludes incompatible models

The selector SHALL filter out candidate models that do not support the required LLM type (chat/embedding/rerank) for the current call point.

#### Scenario: Embedding call filters out chat-only models
- **WHEN** an embedding call point is evaluated
- **THEN** models with only "chat" capability are excluded from candidates
- **AND** only models with "embedding" capability remain

#### Scenario: Rerank call filters out incompatible models
- **WHEN** a rerank call point is evaluated
- **THEN** only models with "rerank" capability are considered

### Requirement: Circuit breaker state filters unavailable providers

The selector SHALL exclude labels belonging to providers whose circuit breaker is OPEN from the candidate pool.

#### Scenario: Provider circuit breaker is open
- **WHEN** provider "aiping" has circuit breaker state = OPEN
- **THEN** all labels with provider="aiping" are excluded from candidate pool
- **AND** only labels from available providers are scored

### Requirement: Per-call-point routing configuration

Each call point SHALL support individual routing mode configuration via `[routing.<call_point>]` section in llm.toml. If no routing configuration exists for a call point, it SHALL fall back to the defaults defined in `[defaults]`.

#### Scenario: Custom mode for classifier
- **WHEN** `[routing.classifier]` section has `mode = "best"`
- **THEN** the classifier call point uses best mode weights

#### Scenario: Fallback to defaults
- **WHEN** no `[routing.<call_point>]` exists for a call point
- **THEN** the call point uses the global default mode weights
