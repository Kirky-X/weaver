## ADDED Requirements

### Requirement: URL encoding detection
The system SHALL detect URL encoding obfuscation techniques.

#### Scenario: Double encoding detected
- **WHEN** URL contains double-encoded characters
- **THEN** returns MEDIUM risk level with "Double URL encoding detected"

#### Scenario: Null byte injection
- **WHEN** URL contains %00 encoding
- **THEN** returns HIGH risk level with "Null byte injection"

#### Scenario: Directory traversal encoding
- **WHEN** URL contains %2e%2e encoding
- **THEN** returns HIGH risk level with "Directory traversal encoding"

### Requirement: Suspicious keyword detection
The system SHALL detect suspicious keywords commonly used in phishing.

#### Scenario: Multiple suspicious keywords
- **WHEN** URL contains 3 or more suspicious keywords
- **THEN** returns HIGH risk level with keyword list

#### Scenario: Single suspicious keyword
- **WHEN** URL contains 1 suspicious keyword
- **THEN** returns MEDIUM risk level with keyword

### Requirement: Domain structure analysis
The system SHALL analyze domain structure for anomalies.

#### Scenario: Excessive subdomain levels
- **WHEN** domain has more than 5 subdomain levels
- **THEN** returns warning about excessive subdomains

#### Scenario: IDN homograph attack
- **WHEN** domain contains xn-- prefix (punycode)
- **THEN** returns warning about potential homograph attack

#### Scenario: Excessive hyphens
- **WHEN** domain contains more than 5 hyphens
- **THEN** returns warning about excessive hyphens

#### Scenario: URL shortener detected
- **WHEN** domain is a known URL shortener
- **THEN** returns LOW risk level with shortener name

### Requirement: Port analysis
The system SHALL detect suspicious port usage.

#### Scenario: Known malicious port
- **WHEN** URL uses port 4444, 5555, or 6667
- **THEN** returns HIGH risk level with port number

#### Scenario: Non-standard port
- **WHEN** URL uses port above 49151
- **THEN** returns MEDIUM risk level with port number

### Requirement: Length analysis
The system SHALL detect abnormally long URLs.

#### Scenario: Very long URL
- **WHEN** URL exceeds 2000 characters
- **THEN** returns MEDIUM risk level with length

#### Scenario: Long URL
- **WHEN** URL exceeds 1000 characters
- **THEN** returns LOW risk level with length

### Requirement: Risk aggregation
The system SHALL aggregate multiple warning into final risk level.

#### Scenario: Multiple issues detected
- **WHEN** multiple heuristic checks fail
- **THEN** returns highest risk level among all checks
- **AND** includes all warnings in result