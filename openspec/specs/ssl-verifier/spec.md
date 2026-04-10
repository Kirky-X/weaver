## ADDED Requirements

### Requirement: Certificate validity check
The system SHALL verify SSL certificate validity.

#### Scenario: Expired certificate
- **WHEN** SSL certificate has expired
- **THEN** returns HIGH risk level with "Certificate has expired"

#### Scenario: Certificate expiring soon
- **WHEN** SSL certificate expires within 7 days
- **THEN** returns MEDIUM risk level with days until expiry

#### Scenario: Valid certificate
- **WHEN** SSL certificate is valid and not expiring soon
- **THEN** returns SAFE risk level

### Requirement: Trust chain verification
The system SHALL verify certificate trust chain.

#### Scenario: Self-signed certificate
- **WHEN** certificate is self-signed
- **THEN** returns HIGH risk level with "Self-signed certificate"

#### Scenario: Unknown CA
- **WHEN** certificate is not from a known trusted CA
- **AND** certificate is not EV
- **THEN** returns MEDIUM risk level with CA name

### Requirement: EV certificate detection
The system SHALL detect Extended Validation certificates.

#### Scenario: EV certificate found
- **WHEN** certificate is EV type
- **THEN** certificate info includes is_ev=true

#### Scenario: Non-EV from trusted CA
- **WHEN** certificate is from trusted CA but not EV
- **THEN** returns SAFE risk level

### Requirement: Connection handling
The system SHALL handle SSL connection errors.

#### Scenario: Connection timeout
- **WHEN** SSL connection times out
- **THEN** returns MEDIUM risk level with "SSL connection timeout"

#### Scenario: SSL error
- **WHEN** SSL handshake fails
- **THEN** returns MEDIUM risk level with error message

#### Scenario: Non-HTTPS URL
- **WHEN** URL scheme is not HTTPS
- **THEN** returns SAFE risk level with "Non-HTTPS URL, SSL check skipped"

### Requirement: SAN analysis
The system SHALL analyze Subject Alternative Names.

#### Scenario: High SAN count
- **WHEN** certificate has more than 50 SANs
- **THEN** returns MEDIUM risk level with SAN count