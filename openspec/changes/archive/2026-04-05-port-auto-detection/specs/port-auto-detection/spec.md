## ADDED Requirements

### Requirement: Port availability detection
The system SHALL detect whether a specified port is available for binding on a given host.

#### Scenario: Port is available
- **WHEN** the system checks port 54321 on host 127.0.0.1
- **AND** the port is not bound by any process
- **THEN** the system SHALL return `True` indicating the port is available

#### Scenario: Port is in use
- **WHEN** the system checks port 54322 on host 127.0.0.1
- **AND** another process is already bound to that port
- **THEN** the system SHALL return `False` indicating the port is unavailable

### Requirement: Bidirectional port search
The system SHALL search for an available port using bidirectional search when the configured port is unavailable.

#### Scenario: Original port is available
- **WHEN** the configured port 8000 is available
- **THEN** the system SHALL use port 8000 without searching

#### Scenario: Original port is unavailable
- **WHEN** the configured port 8000 is unavailable
- **THEN** the system SHALL search in order: 8001, 7999, 8002, 7998, 8003, 7997...
- **AND** the system SHALL skip ports below 1024 (privileged ports)
- **AND** the system SHALL skip ports above 65535
- **AND** the system SHALL return the first available port found

#### Scenario: All ports exhausted
- **WHEN** the system cannot find an available port within `max_attempts` (default 100)
- **THEN** the system SHALL raise `PortExhaustionError`
- **AND** the application SHALL fail to start

### Requirement: Port announcement via multiple channels
The system SHALL announce the actual port being used through multiple channels.

#### Scenario: Port unchanged from configuration
- **WHEN** the resolved port matches the configured port
- **THEN** the system SHALL log `port_check` with `status="available"`
- **AND** the system SHALL NOT write to `.env.weaver`

#### Scenario: Port changed from configuration
- **WHEN** the resolved port differs from the configured port
- **THEN** the system SHALL log `port_resolved` with `original_port` and `actual_port`
- **AND** the system SHALL write `WEAVER_ACTUAL_PORT=<port>` to `.env.weaver`
- **AND** the system SHALL update Prometheus metric `weaver_server_port`

#### Scenario: File write failure
- **WHEN** writing to `.env.weaver` fails
- **THEN** the system SHALL log a warning
- **AND** the system SHALL continue startup (non-critical operation)

### Requirement: Configuration control
The system SHALL allow users to control port auto-detection behavior through configuration.

#### Scenario: Auto-detection enabled (default)
- **WHEN** `port_auto_detect` is `True` (default)
- **THEN** the system SHALL automatically detect and resolve an available port

#### Scenario: Auto-detection disabled
- **WHEN** `port_auto_detect` is `False`
- **THEN** the system SHALL use the configured port directly without detection
- **AND** the application MAY fail to start if the port is unavailable

#### Scenario: Custom max attempts
- **WHEN** `port_max_attempts` is set to a custom value (e.g., 50)
- **THEN** the system SHALL search at most 50 ports before raising `PortExhaustionError`

### Requirement: Docker container support
The system SHALL support port auto-detection in Docker container environments.

#### Scenario: Container startup with dynamic port
- **WHEN** the application starts inside a Docker container
- **AND** `PORT_AUTO_DETECT=true` (environment variable)
- **THEN** the system SHALL detect and use an available port
- **AND** healthcheck SHALL read the actual port from `.env.weaver`

#### Scenario: Healthcheck reads dynamic port
- **WHEN** healthcheck executes
- **THEN** it SHALL read `WEAVER_ACTUAL_PORT` from `.env.weaver`
- **AND** it SHALL check `/health` endpoint on that port