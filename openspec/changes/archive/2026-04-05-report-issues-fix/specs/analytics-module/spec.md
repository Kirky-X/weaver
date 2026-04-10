## REMOVED Requirements

### Requirement: Independent cleanup thread for LLM failures
**Reason**: Scheduler already calls `LLMFailureRepo.cleanup_older_than()` directly via scheduled tasks. The thread-based implementation is redundant.

**Migration**: No migration needed. The `LLMFailureCleanupThread` class is removed, but the core cleanup logic remains in `LLMFailureRepo.cleanup_older_than()` which is already used by the scheduler.

### Requirement: Independent aggregator thread for LLM usage
**Reason**: Scheduler already calls the `_flush()` method directly via scheduled tasks. The thread-based implementation is redundant.

**Migration**: No migration needed. The `LLMUsageAggregatorThread` class is removed, but the core aggregation logic remains in the `_flush()` method which is already used by the scheduler.

### Requirement: Independent cleanup thread for LLM usage raw records
**Reason**: Scheduler already calls `LLMUsageRepo.cleanup_raw_older_than()` directly via scheduled tasks. The thread-based implementation is redundant.

**Migration**: No migration needed. The `RawCleanupThread` class is removed, but the core cleanup logic remains in `LLMUsageRepo.cleanup_raw_older_than()` which is already used by the scheduler.