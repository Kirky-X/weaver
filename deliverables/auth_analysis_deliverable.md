# Authentication Analysis Report

## 1. Executive Summary
- **Analysis Status:** Complete
- **Key Outcome:** Critical authentication flaws were identified, primarily related to lack of transport security, insufficient rate limiting on authentication endpoints, unauthenticated information disclosure, and inadequate API key lifecycle management.
- **Purpose of this Document:** This report provides the strategic context on the application's authentication mechanisms, dominant flaw patterns, and key architectural details necessary to effectively exploit the vulnerabilities listed in the exploitation queue.

### Analysis Scope
- **Application:** Weaver (Python FastAPI knowledge graph platform)
- **Target URL:** http://host.docker.internal:8000
- **Authentication Model:** Stateless API key authentication via `X-API-Key` header
- **Analysis Period:** 2026-04-12
- **Methodology:** White-box code analysis following systematic authentication vulnerability assessment

### Critical Findings Overview
1. **No Transport Layer Security** - API keys transmitted in clear text over HTTP
2. **Four Unauthenticated Information Disclosure Endpoints** - System configuration, version, and metrics exposed without authentication
3. **IP-Based Rate Limiting Only** - No per-API-key rate limiting, enabling brute force attacks from distributed IPs
4. **No API Key Rotation Mechanism** - Compromised keys cannot be replaced without service restart
5. **Error Message Information Leakage** - 401 vs 403 distinction enables user enumeration
6. **Weak Test Credentials in .env File** - Predictable test keys may be deployed accidentally

## 2. Dominant Vulnerability Patterns

### Pattern 1: Absence of Transport Layer Security
- **Description:** The application runs entirely over HTTP without any SSL/TLS configuration. API keys are transmitted in clear text in the `X-API-Key` header on every request. While an HSTS header is present, it is ineffective without HTTPS.
- **Implication:** Attackers can intercept API keys through network sniffing, man-in-the-middle attacks, or by compromising any network intermediary between the client and server. The CORS configuration explicitly allows credentials over HTTP origins, exacerbating this vulnerability.
- **Representative Findings:** `AUTH-VULN-01`, `AUTH-VULN-02`
- **Affected Components:**
  - All 43 protected API endpoints (entire authenticated API surface)
  - API key validation middleware (`src/api/middleware/auth.py`)
  - Uvicorn server configuration (`src/main.py:482-488`)

### Pattern 2: Unauthenticated Information Disclosure
- **Description:** Four operational endpoints (`/health`, `/api/v1/status`, `/api/v1/config`, `/metrics`) are completely unauthenticated and expose detailed system information including version numbers, database types, feature flags, and full Prometheus metrics. This information significantly aids attackers in reconnaissance and vulnerability research.
- **Implication:** Attackers can fingerprint the exact application version, identify technology stack components, discover enabled features, and analyze system performance patterns without any credentials. This violates the principle of least privilege and provides a significant head start for targeted attacks.
- **Representative Findings:** `AUTH-VULN-03`, `AUTH-VULN-04`, `AUTH-VULN-05`, `AUTH-VULN-06`
- **Affected Components:**
  - Health check endpoint (`src/main.py:376-384`)
  - System status endpoint (`src/main.py:386-418`)
  - System config endpoint (`src/main.py:420-436`)
  - Prometheus metrics endpoint (`src/main.py:438-444`)

### Pattern 3: Insufficient Rate Limiting Scope
- **Description:** Rate limiting is implemented using the `slowapi` library but is exclusively IP-based (`get_remote_address`). There is no per-API-key rate limiting, no special rate limits for authentication failures, no CAPTCHA mechanism, and no progressive backoff for repeated failed authentication attempts.
- **Implication:** Attackers can bypass rate limits by distributing authentication attempts across multiple IP addresses (e.g., using botnets, proxy chains, or cloud infrastructure). Brute force attacks, credential stuffing, and password spraying attacks are feasible from distributed sources without triggering the IP-based rate limits.
- **Representative Findings:** `AUTH-VULN-07`
- **Affected Components:**
  - Rate limiter configuration (`src/api/middleware/rate_limit.py`)
  - All endpoints using rate limiting (47 endpoints total)
  - Authentication middleware (`src/api/middleware/auth.py`)

### Pattern 4: Inadequate API Key Lifecycle Management
- **Description:** The application uses a single global API key with no rotation mechanism, no expiration, no invalidation capability, and no support for multiple concurrent keys. Key rotation requires a service restart and immediately invalidates all existing clients. There is no audit trail tracking key usage or concurrent access patterns.
- **Implication:** Compromised keys cannot be replaced gracefully, forcing a choice between continuing to use a compromised key or causing immediate service disruption for all legitimate clients. Zero-downtime key rotation is impossible. There is no way to detect if a key is being shared or abused from multiple locations.
- **Representative Findings:** `AUTH-VULN-08`, `AUTH-VULN-09`
- **Affected Components:**
  - API key storage (`src/config/subconfigs.py:96-148`)
  - API key validation (`src/api/middleware/auth.py:22-75`)
  - Configuration loading (`src/config/settings.py`)

### Pattern 5: Authentication Error Information Leakage
- **Description:** The authentication system returns different HTTP status codes and error messages for missing API keys (401: "Missing API key. Provide X-API-Key header.") versus invalid API keys (403: "Invalid API Key"). This distinction allows attackers to enumerate whether an endpoint requires authentication and whether a provided key format is valid.
- **Implication:** Attackers can use the response differences to verify API key formats, test key validity without triggering invalid authentication attempts, and potentially enumerate users or API keys through systematic probing.
- **Representative Findings:** `AUTH-VULN-10`
- **Affected Components:**
  - API key validation logic (`src/api/middleware/auth.py:44-73`)
  - Error response handlers (`src/api/middleware/api_response.py`)

## 3. Strategic Intelligence for Exploitation

### Authentication Method
The system uses **stateless API key authentication** with the following characteristics:
- **Header:** `X-API-Key` (required on all protected endpoints)
- **Validation:** Timing-safe constant-time comparison using `secrets.compare_digest()`
- **Storage:** Single global key stored in environment variable `WEAVER__API__API_KEY`
- **Key Generation:** Cryptographically secure random generation via `secrets.token_urlsafe(32)` (~43 characters)
- **Minimum Length:** 32 characters enforced in production mode
- **Comparison Method:** Constant-time comparison prevents timing attacks on key validation

### Session Token Details
**Critical for exploitation:** This application does NOT use traditional session management or tokens. There are:
- **No session cookies**
- **No JWT tokens**
- **No refresh tokens**
- **No session storage**
- **No login/logout endpoints**

The API key itself is the only authentication credential and is validated on every request. This is a pure stateless authentication model.

### Rate Limiting Configuration
- **Library:** `slowapi` (a rate limiter for FastAPI/Starlette)
- **Scope:** IP-based only (`get_remote_address`)
- **Default:** 100 requests per minute
- **Endpoint-Specific Limits:**
  - `/api/v1/articles`: 100/minute
  - `/api/v1/search`: 100/minute
  - `/api/v1/search/drift`: 20/minute
  - `/api/v1/search/causal`: 10/minute
  - `/api/v1/search/temporal`: 20/minute
- **No per-API-key limits**
- **No authentication failure rate limits**
- **No CAPTCHA**

### Password Policy
**Not applicable** - The application does not use passwords or user accounts. Authentication is exclusively via API key.

### Configuration Files
- **Environment Variable:** `WEAVER__API__API_KEY`
- **Configuration Files:** `.env`, `config/settings.toml`
- **Priority:** Environment variables > .env file > TOML files > code defaults
- **Test Credentials Found:**
  - `.env`: `test-api-key-32chars-long!!!!`
  - `tests/conftest.py`: `test-api-key` (13 characters, below minimum)

### Security Headers
- **HSTS:** Present (`max-age=31536000; includeSubDomains`) but ineffective without HTTPS
- **X-Frame-Options:** DENY
- **X-Content-Type-Options:** nosniff
- **X-XSS-Protection:** 1; mode=block
- **Cache-Control:** NOT SET on authentication responses
- **Pragma:** NOT SET on authentication responses

### CORS Configuration
- **Allowed Origins:** `http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000` (all HTTP)
- **Allow Credentials:** TRUE
- **Security Implication:** Credentials (API keys) explicitly allowed over insecure HTTP origins

### Unauthenticated Endpoints
The following endpoints require NO authentication:
1. `GET /health` - Health check with service topology
2. `GET /api/v1/status` - Version and database types
3. `GET /api/v1/config` - Feature flags and capabilities
4. `GET /metrics` - Full Prometheus metrics dump
5. `GET /docs` - Swagger UI documentation
6. `GET /redoc` - ReDoc documentation
7. `GET /openapi.json` - OpenAPI schema

### Protected Endpoints
All 43 endpoints under `/api/v1/` (except the four unauthenticated ones above) require valid API key via `X-API-Key` header. This includes all administrative and destructive operations.

### Key Lifecycle
- **Generation:** Automatic via `secrets.token_urlsafe(32)` if not configured
- **Distribution:** Manual (environment variable or configuration file)
- **Validation:** On every request via constant-time comparison
- **Rotation:** Manual environment variable change + service restart
- **Expiration:** None (keys valid indefinitely)
- **Revocation:** None without service restart
- **Grace Period:** None (rotation breaks all clients immediately)

## 4. Secure by Design: Validated Components

These components were analyzed and found to have robust defenses. They are low-priority for further testing.

| Component/Flow | Endpoint/File Location | Defense Mechanism Implemented | Verdict |
|---|---|---|---|
| **Timing-Safe Comparison** | `src/api/middleware/auth.py:69` | Uses `secrets.compare_digest()` for constant-time API key comparison, preventing timing attacks on key validation | SAFE |
| **Cryptographic Key Generation** | `src/config/subconfigs.py:115` | Uses `secrets.token_urlsafe(32)` to generate cryptographically secure random keys with ~43 characters of entropy | SAFE |
| **Minimum Key Length Enforcement** | `src/api/middleware/auth.py:51-68` | Production mode enforces minimum 32-character API keys with HTTP 500 response if not met | SAFE |
| **Environment-Aware Validation** | `src/api/middleware/auth.py:54-68` | Strict validation in production, lenient warnings in development mode | SAFE |
| **Proper HTTP Status Codes** | `src/api/middleware/auth.py:45-73` | Returns 401 for missing keys, 403 for invalid keys, 500 for misconfiguration | SAFE |
| **Request Logging** | `src/main.py:179-256` | Comprehensive HTTP request/response logging with API key prefix (first 8 chars only, not full key) | SAFE |
| **Prometheus Metrics** | `src/core/observability/metrics.py:13-23` | Tracks API request counts and latencies with endpoint, method, and status labels | SAFE |
| **XSS Protection Headers** | `src/main.py:258-279` | SecurityHeadersMiddleware sets X-Content-Type-Options, X-Frame-Options, X-XSS-Protection | SAFE |
| **No Hardcoded Production Keys** | Codebase-wide search | No production API keys hardcoded in source code or committed to repository | SAFE |

## 5. Detailed Vulnerability Analysis

### 5.1 Transport Security Vulnerabilities

#### AUTH-VULN-01: API Key Transmission Over Clear Text HTTP
- **Type:** Transport_Exposure
- **Severity:** Critical
- **Description:** The application runs entirely over HTTP without SSL/TLS. The `X-API-Key` header containing the API key is transmitted in clear text on every request to protected endpoints.
- **Vulnerable Code Location:** `src/main.py:482-488` (uvicorn configuration lacks ssl_keyfile/ssl_certfile)
- **Missing Defense:** No SSL/TLS termination, no HTTPS redirect, no secure transport enforcement
- **Exploitation Hypothesis:** An attacker on the same network or any network intermediary can intercept the API key by sniffing HTTP traffic and then use that key to authenticate to the API.
- **Suggested Exploit Technique:** `credential_sniffing` - Capture network traffic and extract X-API-Key header

#### AUTH-VULN-02: Ineffective HSTS Header
- **Type:** Transport_Exposure
- **Severity:** Medium
- **Description:** The application sets the `Strict-Transport-Security` header with `max-age=31536000; includeSubDomains`, but this is ineffective because the application is served over HTTP, not HTTPS.
- **Vulnerable Code Location:** `src/main.py:268` (SecurityHeadersMiddleware sets HSTS header)
- **Missing Defense:** HSTS requires HTTPS to be effective; the header is meaningless on HTTP responses
- **Exploitation Hypothesis:** The HSTS header provides no actual protection because connections are already over HTTP. An attacker can continue intercepting traffic.
- **Suggested Exploit Technique:** `credential_sniffing` - HSTS does not prevent HTTP MITM attacks

#### AUTH-VULN-03: CORS Allows Credentials Over HTTP Origins
- **Type:** Transport_Exposure
- **Severity:** High
- **Description:** The CORS configuration explicitly sets `allow_credentials=True` and allows origins like `http://localhost:3000`, enabling API key transmission over insecure HTTP origins.
- **Vulnerable Code Location:** `src/main.py:344-354` (CORSMiddleware configuration)
- **Missing Defense:** CORS origins should be HTTPS-only when credentials are enabled
- **Exploitation Hypothesis:** A malicious HTTP page can make authenticated requests to the API and capture API keys if the browser allows cross-origin requests with credentials.
- **Suggested Exploit Technique:** `credential_sniffing` - CORS-based credential capture

### 5.2 Unauthenticated Information Disclosure

#### AUTH-VULN-04: System Version Disclosure
- **Type:** Authentication_Bypass (information disclosure)
- **Severity:** Medium
- **Description:** The `/api/v1/status` endpoint returns the exact application version from `pyproject.toml` without requiring authentication.
- **Vulnerable Code Location:** `src/main.py:386-418`
- **Missing Defense:** No `Depends(verify_api_key)` dependency on the endpoint
- **Exploitation Hypothesis:** An attacker can query `/api/v1/status` to obtain the exact version number, then look up CVEs and version-specific vulnerabilities for targeted attacks.
- **Suggested Exploit Technique:** `version_fingerprinting` - Query endpoint, extract version, research specific vulnerabilities

#### AUTH-VULN-05: Technology Stack Disclosure
- **Type:** Authentication_Bypass (information disclosure)
- **Severity:** Medium
- **Description:** The `/api/v1/status` and `/api/v1/config` endpoints expose database types (PostgreSQL, Neo4j, Redis) and feature flags without authentication.
- **Vulnerable Code Location:** `src/main.py:386-436`
- **Missing Defense:** No authentication required on technology stack information
- **Exploitation Hypothesis:** Attackers can identify the exact technology stack and enabled features for targeted vulnerability research without any credentials.
- **Suggested Exploit Technique:** `tech_stack_fingerprinting` - Extract database types and features for targeted attacks

#### AUTH-VULN-06: Detailed Prometheus Metrics Exposure
- **Type:** Authentication_Bypass (information disclosure)
- **Severity:** Medium
- **Description:** The `/metrics` endpoint exposes full Prometheus metrics including request patterns, latency data, and error rates without any authentication.
- **Vulnerable Code Location:** `src/main.py:438-444`
- **Missing Defense:** No authentication on Prometheus metrics endpoint
- **Exploitation Hypothesis:** Attackers can analyze system performance patterns, request volumes, and timing information to plan attacks or identify optimal timing for exploitation.
- **Suggested Exploit Technique:** `metrics_analysis` - Extract operational intelligence for attack planning

### 5.3 Rate Limiting and Abuse Prevention

#### AUTH-VULN-07: IP-Only Rate Limiting Bypass
- **Type:** Abuse_Defenses_Missing
- **Severity:** High
- **Description:** Rate limiting is implemented using `slowapi` with `get_remote_address` as the key function, meaning limits are per-IP only. There is no per-API-key rate limiting, allowing distributed brute force attacks.
- **Vulnerable Code Location:** `src/api/middleware/rate_limit.py:9` (limiter uses get_remote_address)
- **Missing Defense:** No per-API-key rate limiting, no progressive backoff for auth failures, no CAPTCHA
- **Exploitation Hypothesis:** An attacker can distribute authentication attempts across multiple IP addresses (using botnets, proxies, or cloud infrastructure) to bypass IP-based rate limits and brute force API keys.
- **Suggested Exploit Technique:** `distributed_brute_force` - Distribute auth attempts across multiple IPs to bypass rate limiting

### 5.4 API Key Management Issues

#### AUTH-VULN-08: No API Key Rotation Mechanism
- **Type:** Token_Management_Issue
- **Severity:** High
- **Description:** The application supports only a single global API key stored in an environment variable. There is no rotation mechanism, no support for multiple concurrent keys, and no graceful transition path for key updates.
- **Vulnerable Code Location:** `src/config/subconfigs.py:96-124` (single api_key field in APISettings)
- **Missing Defense:** No key rotation endpoints, no multiple key support, no key versioning
- **Exploitation Hypothesis:** Once an API key is compromised, it cannot be replaced without causing immediate service disruption for all legitimate clients. Organizations may continue using compromised keys to avoid downtime.
- **Suggested Exploit Technique:** `credential_persistence` - Compromised keys remain valid indefinitely without rotation capability

#### AUTH-VULN-09: No API Key Expiration or Invalidation
- **Type:** Token_Management_Issue
- **Severity:** High
- **Description:** API keys have no expiration date and cannot be invalidated without a service restart. There is no key revocation mechanism or blacklist.
- **Vulnerable Code Location:** `src/api/middleware/auth.py:44-75` (validation only checks key validity, no expiration logic)
- **Missing Defense:** No TTL, no expiration checking, no revocation list, no hot-reload for key updates
- **Exploitation Hypothesis:** A compromised API key remains valid forever until manually changed, giving attackers unlimited time to exfiltrate data or maintain persistent access.
- **Suggested Exploit Technique:** `persistent_access` - Compromised keys provide indefinite access without expiration

### 5.5 Authentication Logic Issues

#### AUTH-VULN-10: User Enumeration via Error Response Distinction
- **Type:** Login_Flow_Logic
- **Severity:** Low
- **Description:** The authentication system returns different HTTP status codes for missing API keys (401) versus invalid API keys (403), allowing attackers to distinguish between these states.
- **Vulnerable Code Location:** `src/api/middleware/auth.py:44-73` (different status codes for missing vs invalid)
- **Missing Defense:** Generic error responses that don't distinguish between missing and invalid credentials
- **Exploitation Hypothesis:** An attacker can use the 401 vs 403 distinction to verify authentication requirements and potentially enumerate valid key formats or test key validity patterns.
- **Suggested Exploit Technique:** `user_enumeration` - Analyze error responses to extract information about authentication state

### 5.6 Default Credentials

#### AUTH-VULN-11: Weak Test Credentials in .env File
- **Type:** Weak_Credentials
- **Severity:** Medium
- **Description:** The `.env` file contains weak, predictable test API keys (`test-api-key-32chars-long!!!!`) that may accidentally be deployed to production.
- **Vulnerable Code Location:** `.env:27` (contains weak test credentials)
- **Missing Defense:** No validation preventing weak credentials in production, no secrets management
- **Exploitation Hypothesis:** If the .env file or test credentials are accidentally deployed to production, attackers can guess or use the predictable test API key to authenticate.
- **Suggested Exploit Technique:** `credential_stuffing` - Try common test credentials like `test-api-key-32chars-long!!!!`

## 6. Attack Scenario Summaries

### Scenario 1: Network Sniffing for API Key Capture
1. Attacker positions themselves on the same network as a legitimate API client
2. Attacker runs packet capture (tcpdump, Wireshark) on the network
3. Legitimate client makes API requests to http://host.docker.internal:8000
4. Attacker extracts `X-API-Key` header from captured HTTP packets
5. Attacker uses the captured API key to authenticate to the API

**Vulnerabilities Exploited:** AUTH-VULN-01, AUTH-VULN-02, AUTH-VULN-03

### Scenario 2: Distributed Brute Force Attack
1. Attacker obtains a list of potential API keys (from wordlists, breaches, or test credentials)
2. Attacker distributes authentication attempts across multiple IP addresses (botnet, cloud infrastructure, proxies)
3. Each IP sends authentication attempts below the 100/minute rate limit
4. Attacker aggregates results to identify valid API keys
5. Valid keys are used for unauthorized access

**Vulnerabilities Exploited:** AUTH-VULN-07, AUTH-VULN-10

### Scenario 3: Information Disclosure for Targeted Attacks
1. Attacker queries `/api/v1/status` to obtain exact version number
2. Attacker queries `/api/v1/config` to identify enabled features and technology stack
3. Attacker queries `/metrics` to analyze system patterns and identify optimal attack timing
4. Attacker researches CVEs for the specific version and technologies
5. Attacker launches targeted exploitation attempts

**Vulnerabilities Exploited:** AUTH-VULN-04, AUTH-VULN-05, AUTH-VULN-06

### Scenario 4: Persistent Access via Compromised Key
1. Attacker obtains API key through any means (sniffing, brute force, social engineering)
2. Attacker uses API key to access all 43 protected endpoints including admin operations
3. Attacker exfiltrates data, modifies configurations, or deletes resources
4. Even if compromise is detected, key cannot be invalidated without service restart
5. Attacker maintains access indefinitely with the compromised key

**Vulnerabilities Exploited:** AUTH-VULN-08, AUTH-VULN-09

## 7. Recommendations

### Immediate Actions (Critical)
1. **Enable HTTPS/TLS** - Configure SSL/TLS termination on the application or reverse proxy
2. **Restrict Unauthenticated Endpoints** - Add authentication to `/api/v1/status`, `/api/v1/config`, `/metrics`
3. **Implement Per-API-Key Rate Limiting** - Change rate limiter to use API key as the limiting factor
4. **Remove Test Credentials** - Delete weak test keys from `.env` and other configuration files

### Short-Term Actions (High Priority)
5. **Add Cache-Control Headers** - Set `Cache-Control: no-store, no-cache` on authentication responses
6. **Implement API Key Rotation** - Add support for multiple valid keys and rotation endpoints
7. **Add Key Expiration** - Implement TTL for API keys with automatic expiration
8. **Generic Error Responses** - Use identical error messages for all authentication failures

### Long-Term Actions (Medium Priority)
9. **Implement Key Management System** - Database-backed key storage with metadata and audit logging
10. **Add CAPTCHA** - Implement CAPTCHA for repeated authentication failures
11. **Concurrent Usage Tracking** - Detect and alert on multiple IPs using the same key
12. **Key Scoping** - Implement per-client keys with scoped permissions

## 8. Conclusion

The Weaver application's authentication model has critical vulnerabilities stemming from its stateless API key architecture and lack of transport security. The most severe issues are:

1. **Clear text API key transmission** enabling credential interception
2. **Unauthenticated information disclosure** providing attack intelligence
3. **IP-only rate limiting** allowing distributed brute force attacks
4. **No key rotation mechanism** forcing organizations to use compromised keys

The application demonstrates some secure practices (timing-safe comparison, cryptographic key generation, minimum key length enforcement), but these are undermined by the architectural limitations of the single-key, stateless authentication model.

All identified vulnerabilities are externally exploitable without requiring internal network access, VPN, or direct server access. The exploitation queue provides specific, actionable hypotheses for the exploitation phase.


