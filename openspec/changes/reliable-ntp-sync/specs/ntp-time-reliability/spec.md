## ADDED Requirements

### Requirement: Concurrent NTP probing
The system SHALL send NTP requests to all configured servers simultaneously and accept the first successful response.

#### Scenario: Fastest server wins
- **WHEN** multiple NTP servers are reachable with different latencies
- **THEN** the response from the fastest server is used and other pending requests are abandoned

#### Scenario: All servers unreachable within timeout
- **WHEN** no NTP server responds within the timeout period
- **THEN** the function returns None and logs a warning

### Requirement: NTP timeout of 1 second
The NTP request timeout SHALL be set to 1 second for all server requests.

#### Scenario: Timeout enforced
- **WHEN** an NTP server does not respond within 1 second
- **THEN** that server's request is considered failed and does not block the overall result

### Requirement: Extended NTP server list
The NTP server list SHALL include at least 5 servers with domestic (China) servers prioritized: ntp.aliyun.com, ntp.tencent.com, pool.ntp.org, cn.ntp.org.cn, and time.google.com.

#### Scenario: Server list is accessible
- **WHEN** the module is loaded
- **THEN** the server list contains at least 5 entries with domestic servers listed first

### Requirement: TTL-based time caching
The system SHALL cache successful NTP time results for 3600 seconds (1 hour) using an in-memory cache.

#### Scenario: Cache hit returns stored time
- **WHEN** a cached NTP time result exists and has not expired
- **THEN** the cached time is returned immediately without any network request

#### Scenario: Cache miss triggers NTP probe
- **WHEN** the cache is empty or has expired
- **THEN** a new NTP probe is executed and the result is stored in the cache

#### Scenario: Cache expires after 1 hour
- **WHEN** 3600 seconds have passed since the last successful cache write
- **THEN** the next call performs a fresh NTP probe

### Requirement: Graceful fallback to local time
When NTP probing fails (all servers unreachable or timeout), the system SHALL fall back to the local system time without raising an exception.

#### Scenario: All NTP servers fail
- **WHEN** no NTP server responds successfully
- **THEN** the local system time with timezone is returned

### Requirement: Informative logging
NTP probe failures SHALL be logged at INFO level for individual server failures and WARNING level when all servers fail.

#### Scenario: Single server failure logged
- **WHEN** an individual NTP server fails to respond
- **THEN** an INFO-level log entry records the server name and error

#### Scenario: Total failure logged
- **WHEN** all NTP servers fail to respond
- **THEN** a WARNING-level log entry records the total failure
