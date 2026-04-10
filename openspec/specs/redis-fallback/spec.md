## ADDED Requirements

### Requirement: Graceful Redis failure handling
Deduplicator SHALL fall back to database queries when Redis is unavailable.

#### Scenario: Redis down falls back to DB
- **WHEN** Redis connection fails during deduplication
- **THEN** deduplicator queries PostgreSQL for existing URLs
- **AND** processing continues without interruption
- **AND** warning is logged for monitoring

#### Scenario: Redis timeout triggers fallback
- **WHEN** Redis operation times out (> 5 seconds)
- **THEN** fallback to DB query is triggered
- **AND** Redis connection is marked unhealthy for subsequent calls

### Requirement: Redis health tracking
The system SHALL track Redis health status and automatically recover.

#### Scenario: Redis recovers after outage
- **WHEN** Redis becomes available after being marked unhealthy
- **THEN** next deduplication call uses Redis
- **AND** health status is updated to healthy

#### Scenario: Redis health check interval
- **WHEN** Redis has been unhealthy for 60 seconds
- **THEN** a health check probe is attempted
- **AND** if successful, Redis is restored to active use

### Requirement: Fallback mode indicator
The system SHALL provide visibility into fallback mode operation.

#### Scenario: Metrics track fallback usage
- **WHEN** fallback mode is active
- **THEN** Prometheus metric `weaver_redis_fallback_total` is incremented
- **AND** Grafana dashboard shows fallback percentage