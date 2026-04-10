## ADDED Requirements

### Requirement: Prompt content is cached with configurable TTL

The system SHALL cache prompt content in memory with a configurable time-to-live (TTL) to reduce database queries.

#### Scenario: Cache hit returns cached content
- **WHEN** requesting prompt "classifier" type "system" and it exists in cache
- **THEN** the system SHALL return the cached content without database query

#### Scenario: Cache miss queries database
- **WHEN** requesting prompt "classifier" type "system" and it does not exist in cache
- **THEN** the system SHALL query the database, cache the result, and return the content

#### Scenario: Configurable TTL
- **WHEN** `cache_ttl_seconds = 7200` (2 hours)
- **THEN** cached entries SHALL expire after 7200 seconds

---

### Requirement: Cache uses CachePool protocol

The system SHALL use the `CachePool` protocol for cache operations, supporting both Redis and Cashews fallback implementations.

#### Scenario: Redis cache backend
- **WHEN** Redis is available and configured
- **THEN** the system SHALL use RedisClient for cache storage

#### Scenario: Cashews fallback
- **WHEN** Redis is unavailable
- **THEN** the system SHALL use CashewsRedisFallback for in-memory cache storage

---

### Requirement: Cache invalidation on prompt update

The system SHALL invalidate cached prompts when the prompt is updated or a different version is activated.

#### Scenario: Invalidate on update
- **WHEN** prompt "classifier" content is updated
- **THEN** the system SHALL delete all cache entries for "classifier" (all types)

#### Scenario: Invalidate on version activation
- **WHEN** version "1.0.0" is activated for prompt "classifier"
- **THEN** the system SHALL delete all cache entries for "classifier"

---

### Requirement: Hot reload clears cache

The system SHALL support hot reload that clears cached prompts, forcing fresh reads from database on next access.

#### Scenario: Hot reload single prompt
- **WHEN** calling `reload("classifier")`
- **THEN** the system SHALL delete all cache entries for "classifier"

#### Scenario: Hot reload all prompts
- **WHEN** calling `reload()` without arguments
- **THEN** the system SHALL clear all cached prompts

---

### Requirement: Cache can be disabled

The system SHALL support disabling cache via configuration (`cache_enabled = false`).

#### Scenario: Cache disabled always queries database
- **WHEN** `cache_enabled = false`
- **THEN** all prompt requests SHALL query the database directly

#### Scenario: Cache disabled ignores TTL
- **WHEN** `cache_enabled = false`
- **THEN** the system SHALL not use any caching regardless of TTL configuration

---

### Requirement: Cache key format is standardized

The system SHALL use standardized cache key format for prompt storage.

#### Scenario: Content cache key
- **WHEN** caching prompt content
- **THEN** the cache key SHALL be `prompt:{name}:{type}` (e.g., `prompt:classifier:system`)

#### Scenario: Version cache key
- **WHEN** caching prompt version
- **THEN** the cache key SHALL be `prompt:{name}:version` (e.g., `prompt:classifier:version`)