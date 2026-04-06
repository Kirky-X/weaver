## 1. Setup

- [x] 1.1 Add URLSecuritySettings to src/config/settings.py
- [x] 1.2 Create src/core/security/models.py with URLRisk, CheckSource, CheckResult, ValidationResult
- [x] 1.3 Create src/core/security/ssrf.py by extracting SSRFChecker from url_validator.py
- [x] 1.4 Create src/core/security/cache.py with URLSecurityCache

## 2. HttpxFetcher Extension

- [x] 2.1 Add post() method to HttpxFetcher class
- [x] 2.2 Add unit tests for HttpxFetcher.post()

## 3. Malicious URL Checkers

- [x] 3.1 Create src/core/security/malicious_url/__init__.py
- [x] 3.2 Create src/core/security/malicious_url/urlhaus_client.py
- [x] 3.3 Create src/core/security/malicious_url/phishtank_sync.py
- [x] 3.4 Create src/core/security/malicious_url/heuristic_checker.py
- [x] 3.5 Create src/core/security/malicious_url/ssl_verifier.py

## 4. URLValidator Facade

- [x] 4.1 Create src/core/security/validator.py with URLValidator class
- [x] 4.2 Update src/core/security/__init__.py with new exports
- [x] 4.3 Remove src/core/security/url_validator.py (migrated to new modules)

## 5. Integration

- [x] 5.1 Update container.py to register URLValidator with dependency injection
- [x] 5.2 Add PhishTank sync to scheduler jobs
- [x] 5.3 Update HttpxFetcher instantiation to use new URLValidator

## 6. Testing

- [x] 6.1 Add unit tests for SSRFChecker
- [x] 6.2 Add unit tests for URLhausClient (mock API responses)
- [x] 6.3 Add unit tests for PhishTankSync
- [x] 6.4 Add unit tests for HeuristicChecker
- [x] 6.5 Add unit tests for SSLVerifier
- [x] 6.6 Add unit tests for URLValidator (integration tests with mocks)
- [x] 6.7 Add unit tests for URLSecurityCache

## 7. Documentation

- [x] 7.1 Update README with URL security configuration options
- [x] 7.2 Add inline docstrings for all public APIs
