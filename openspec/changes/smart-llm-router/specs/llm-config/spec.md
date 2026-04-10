## ADDED Requirements

### Requirement: Circuit breaker tracks slow requests

The circuit breaker SHALL track not only failures but also slow requests. A request is considered "slow" if its latency exceeds the provider's configured timeout multiplied by a configurable slow_threshold (default: 0.5, meaning 50% of timeout).

#### Scenario: Slow request recorded
- **WHEN** a request completes successfully but takes 80 seconds with a 120s timeout
- **THEN** the request is not counted as a failure
- **AND** the slow_request_count is incremented

#### Scenario: Consecutive slow requests trigger degradation
- **WHEN** a provider has 5 consecutive slow requests
- **THEN** the provider's editorial score is reduced by 50% for subsequent selections
- **AND** the circuit breaker state remains CLOSED (not opened)

### Requirement: CircuitOpenError for open circuit rejection

When a provider's circuit breaker is OPEN, any attempt to execute a call through that provider SHALL raise CircuitOpenError immediately, without attempting the call or consuming retry budget.

#### Scenario: Circuit open during execution
- **WHEN** ProviderPool.execute() is called and the target provider's circuit breaker is OPEN
- **THEN** CircuitOpenError is raised
- **AND** the label is skipped to the next fallback candidate
