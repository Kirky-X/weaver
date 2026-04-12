# Penetration Test Scope & Boundaries

**Primary Directive:** This analysis is strictly limited to the **network-accessible attack surface** of the application. All subsequent tasks must adhere to this scope. Before reporting any finding (e.g., an entry point, a vulnerability sink), it must first meet the "In-Scope" criteria.

### In-Scope: Network-Reachable Components
A component is considered **in-scope** if its execution can be initiated, directly or indirectly, by a network request that the deployed application server is capable of receiving. This includes:
- Publicly exposed web pages and API endpoints.
- Endpoints requiring authentication via the application's standard login mechanisms.
- Any developer utility, debug console, or script that has been mistakenly exposed through a route or is otherwise callable from other in-scope, network-reachable code.

### Out-of-Scope: Locally Executable Only
A component is **out-of-scope** if it **cannot** be invoked through the running application's network interface and requires an execution context completely external to the application's request-response cycle. This includes tools that must be run via:
- A command-line interface (e.g., `python scripts/...`).
- A development environment's internal tooling.
- CI/CD pipeline scripts or build tools.
- Database migration scripts, backup tools, or maintenance utilities.
- Local development servers, test harnesses, or debugging utilities.
- Static files or scripts that require manual opening in a browser.

---

## 1. Executive Summary

**Weaver** is a Python-based knowledge graph construction and intelligence platform built on FastAPI 0.135.1. It ingests content from RSS feeds and web sources, processes it through LLM-powered pipelines (via litellm with multiple providers), and constructs searchable knowledge graphs stored across PostgreSQL (with pgvector), Neo4j, Redis, and DuckDB. The application exposes a comprehensive REST API under `/api/v1/` with approximately 40+ endpoints covering source management, content ingestion/pipeline processing, article retrieval, advanced search (including causal, temporal, and DRIFT search modes), knowledge graph operations, graph visualization, and administrative functions.

The most critical attack surfaces identified are: (1) **Unauthenticated information disclosure endpoints** (`/api/v1/config`, `/api/v1/status`, `/metrics`) that expose system configuration, database connection details, and Prometheus metrics without any authentication; (2) **SSRF via Crawl4AI bypass** where the browser-based fallback crawler (`crawl4ai_fetcher.py`) does not apply SSRF validation, allowing internal network scanning when users submit source URLs; (3) **SQL injection in migration adapters** where table and index names are interpolated into SQL queries via f-strings; and (4) **Single API key authorization model** with no role-based access control, meaning any compromised key grants full administrative access including data manipulation and system reconfiguration.

The application demonstrates several security strengths including constant-time API key comparison, comprehensive SSRF protection on the primary HTTP fetch path, security headers middleware, request size limiting, rate limiting, and structured log sanitization. However, the single-key auth model, lack of encryption at rest, absent multi-tenant isolation, and the Crawl4AI SSRF gap represent significant weaknesses that a penetration tester should prioritize.

---

## 2. Architecture & Technology Stack

### Framework & Language
The application is built on **Python 3.12** with **FastAPI 0.135.1** as the web framework, served by **Uvicorn** (ASGI server). Data validation uses **Pydantic v2** with **pydantic-settings** for configuration management. The project uses the **UV** package manager for dependency management with dependencies declared in `pyproject.toml` and locked in `uv.lock`.

**Security implications of the stack:** FastAPI's automatic OpenAPI documentation generation (accessible at `/docs` and `/redoc` by default) may expose the full API surface to unauthenticated users. Pydantic provides strong input validation, but the effectiveness depends on schema completeness per endpoint. The use of async SQLAlchemy 2.0 with asyncpg provides parameterized query support by default, though raw SQL via `text()` is used in migration adapters, creating injection risks.

### Architectural Pattern
Weaver follows a **Clean Architecture / Hexagonal Design** with dependency injection via a custom container (`src/container.py`). The codebase is organized into distinct layers:

- **API Layer** (`src/api/`): FastAPI routers, middleware, and request/response schemas
- **Core Layer** (`src/core/`): Infrastructure including database connections, LLM clients, NLP processing, caching, observability, security utilities, and resilience patterns
- **Modules Layer** (`src/modules/`): Business logic organized by domain (ingestion, knowledge, processing, storage, analytics, migration, scheduler)

**Trust boundary analysis:** The primary trust boundary exists at the API middleware layer where API key authentication is enforced. A secondary trust boundary exists between the application and external services (LLM providers, crawled websites). The application trusts its database layer completely — there is no inter-service authentication between the API and database tiers. The Crawl4AI fetcher operates outside the normal SSRF validation trust boundary, representing a gap where external user-controlled URLs can trigger browser-based requests to arbitrary destinations.

### Critical Security Components
- **API Key Authentication**: `src/api/middleware/auth.py` — uses `X-API-Key` header with constant-time comparison via `secrets.compare_digest()` and minimum 32-character key length enforcement
- **SSRF Protection**: `src/core/security/validation/ssrf.py` — blocks RFC 1918 ranges, cloud metadata endpoints, loopback, and IPv6 private ranges with DNS resolution verification
- **URL Validator**: `src/core/security/validation/validator.py` — multi-layered URL validation combining SSRF checks, URLhaus API, PhishTank blacklist, heuristic analysis, and SSL verification
- **Security Headers Middleware**: `src/main.py` (SecurityHeadersMiddleware) — applies X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, and HSTS headers
- **Rate Limiting**: `src/api/middleware/rate_limit.py` — slowapi-based rate limiting at 100 requests/minute (configurable)
- **Request Size Limiter**: `src/main.py` — custom ASGI middleware enforcing 10MB maximum request body
- **Log Sanitization**: `src/core/utils/sanitize.py` — masks passwords, API keys, tokens, and connection strings in logs
- **HMAC Data Signing**: `src/core/security/crypto/signing.py` — SHA256 HMAC for data integrity verification
- **Safe Query Utilities**: `src/core/db/safe_query.py` — regex-based validation for SQL identifiers and Neo4j labels

### Database Architecture
The application uses a multi-database approach:
- **PostgreSQL 16** with **pgvector**: Primary relational storage for articles, vectors, and metadata. Connection pooling (20 initial, 10 max overflow) via async SQLAlchemy with asyncpg.
- **Neo4j 5.25** with **APOC plugin**: Graph database for knowledge graph entity relationships and community detection. Incremental sync with PostgreSQL.
- **Redis 7.2**: Caching layer for session data, rate limiting state, and temporary storage.
- **DuckDB 1.5.1**: Fallback analytics storage for LLM usage tracking and temporary data (local file-based, no network exposure).

**Security concern:** Database connections are configured without explicit SSL/TLS enforcement in the connection strings found in `src/core/db/postgres.py` and `src/core/db/neo4j.py`, meaning database traffic may be unencrypted in transit.

---

## 3. Authentication & Authorization Deep Dive

### Authentication Mechanisms
Weaver implements a single authentication mechanism: **API Key authentication** via the `X-API-Key` HTTP header. The implementation is located in `src/api/middleware/auth.py` (lines 16-75).

**How it works:** The `verify_api_key` function is a FastAPI dependency that extracts the API key from the `X-API-Key` header using `APIKeyHeader`. It performs constant-time comparison using `secrets.compare_digest()` (line 69) against the configured API key, preventing timing attacks. A minimum API key length of 32 characters is enforced during configuration validation (`src/config/subconfigs.py`, line 19). In production mode, warnings are emitted if the API key appears to be a development default.

**API Key endpoints (exhaustive list):**
- There are **no dedicated login/logout/token-refresh endpoints** — authentication is stateless and per-request via the API key header
- There is **no password-based authentication** — the application does not implement user accounts
- There is **no OAuth/OIDC/SSO** — no third-party identity provider integration exists

### Session Management and Token Security
The application is **stateless** — there are no session cookies, JWT tokens, or session management mechanisms. Each request must include the `X-API-Key` header. This means:
- **No session cookie flags** (`HttpOnly`, `Secure`, `SameSite`) are configured because no cookies are used for authentication
- **No token expiration** — the API key does not expire unless manually rotated
- **No token refresh** — the same API key is used indefinitely
- **No concurrent session control** — the API key can be used from unlimited locations simultaneously

### Authorization Model and Potential Bypass Scenarios
The authorization model is **flat**: a single API key grants full access to ALL endpoints, including administrative functions. There is no role-based access control (RBAC), no user-specific permissions, and no differentiation between read-only and administrative operations.

**Bypass scenarios:**
1. **Single key compromise = full system compromise**: An attacker who obtains the API key gains access to all endpoints including admin functions like `/api/v1/admin/authorities`, `/api/v1/admin/articles/deduplicate`, community rebuilding, and system configuration access.
2. **No privilege separation**: There is no way to issue limited-scope keys for different clients or services.
3. **Key rotation requires full service restart**: Changing the API key requires updating the environment variable and restarting the service, with no graceful rotation mechanism.

### Multi-Tenancy Security Implementation
**There is no multi-tenancy implementation.** All data is stored in a shared database with no tenant isolation fields (`tenant_id`, `organization_id`) in data models (`src/core/db/models.py`). Any authenticated user with the API key has access to all data across the entire system. This is a significant architectural gap for any multi-user deployment scenario.

### SSO/OAuth/OIDC Flows
**Not applicable.** No SSO, OAuth, OIDC, or SAML configurations exist in the codebase. There are no callback endpoints, no state/nonce validation code, and no third-party identity provider integrations.

---

## 4. Data Security & Storage

### Database Security
**Connection encryption:** Database connections to PostgreSQL and Neo4j are configured without explicit SSL/TLS enforcement. In `src/core/db/postgres.py` (lines 61-72), the connection uses asyncpg with no `sslmode` parameter — defaulting to no encryption. Similarly, `src/core/db/neo4j.py` (line 30) creates a Neo4j driver without enforcing encrypted connections. DuckDB is file-based (`axon.db`, `axon.db.wal` in the project root) and has no network exposure.

**Query safety:** The application primarily uses SQLAlchemy ORM for database operations, which provides parameterized queries by default. However, `src/core/db/safe_query.py` provides additional regex-based validation for SQL identifiers. Despite this, the migration adapters in `src/modules/migration/adapters/postgres_target.py` (lines 89, 116) and `src/modules/migration/adapters/duckdb_target.py` (lines 115, 175) use f-string interpolation for table and index names in SQL queries, creating SQL injection potential if those values are attacker-controlled.

**Neo4j query safety:** Neo4j Cypher queries consistently use parameterized queries via `session.run(query, parameters or {})` with proper parameter binding. No string interpolation was found in Cypher query construction.

### Data Flow Security
**Sensitive data flows:**
1. **Source URL submission → Web crawling**: User-submitted URLs in POST `/api/v1/sources` and POST `/api/v1/pipeline/url` flow through the SmartFetcher and Crawl4AI fetchers to make outbound HTTP requests. The primary path applies SSRF validation, but the Crawl4AI fallback does not.
2. **Article content → LLM processing**: Article content is sent to LLM providers via litellm for entity extraction, summarization, and relationship detection. LLM API base URLs are configurable and not validated against SSRF protections.
3. **Search queries → LLM processing**: Advanced search endpoints (causal, temporal, DRIFT) send user queries directly to LLM models for reasoning, creating potential for prompt injection attacks against the LLM layer.
4. **API key transmission**: The API key is transmitted via HTTP header on every request. Without HSTS enforcement at the infrastructure level (the application sets HSTS headers but the client must honor them), the key could be intercepted in a MITM scenario.

### Multi-Tenant Data Isolation
**No multi-tenant isolation exists.** All database models in `src/core/db/models.py` lack tenant or organization identifiers. All API endpoints return data without any tenant-scoped filtering. The Article model (lines 152-167) stores URLs, titles, and full content without encryption at rest. Any authenticated user can access all articles, sources, graph data, and community reports across the entire system.

---

## 5. Attack Surface Analysis

### External Entry Points

#### Unauthenticated Endpoints (HIGH PRIORITY)

| Endpoint | Method | Risk |
|----------|--------|------|
| `/health` | GET | Exposes health status — low risk, standard for load balancers |
| `/api/v1/status` | GET | **HIGH RISK**: Exposes system status including database information without authentication |
| `/api/v1/config` | GET | **CRITICAL RISK**: Exposes current application configuration without authentication — may reveal database hosts, API endpoints, and internal service details |
| `/metrics` | GET | **HIGH RISK**: Exposes Prometheus metrics without authentication — reveals application internals, request patterns, and performance data |
| `/docs` (FastAPI default) | GET | **MEDIUM RISK**: Auto-generated OpenAPI documentation exposing full API schema |
| `/redoc` (FastAPI default) | GET | **MEDIUM RISK**: Alternative API documentation UI |
| `/openapi.json` (FastAPI default) | GET | **MEDIUM RISK**: Machine-readable OpenAPI schema |

**Critical finding:** The `/api/v1/config` endpoint exposes the application's running configuration without any authentication. The `/api/v1/status` endpoint exposes database connection status and system health. These are verified as unauthenticated by the absence of `Depends(verify_api_key)` in their endpoint definitions. An external attacker can enumerate the full technology stack, database hosts, LLM provider configurations, and internal service endpoints by simply calling these endpoints.

#### Authenticated API Endpoints (API Key Required)

**Source Management** (`/api/v1/sources`):
- `GET /api/v1/sources` — List all sources (with `enabled_only` filter)
- `GET /api/v1/sources/{source_id}` — Get source details
- `POST /api/v1/sources` — **Create new source with user-controlled URL** (SSRF vector)
- `PUT /api/v1/sources/{source_id}` — **Update source URL** (SSRF vector)
- `DELETE /api/v1/sources/{source_id}` — Delete source

**Pipeline Processing** (`/api/v1/pipeline`):
- `POST /api/v1/pipeline/trigger` — Trigger crawl pipeline (initiates outbound HTTP requests to source URLs)
- `GET /api/v1/pipeline/tasks/{task_id}` — Query pipeline task status
- `GET /api/v1/pipeline/queue/stats` — Get queue statistics
- `POST /api/v1/pipeline/url` — **Process a single URL through full pipeline** (SSRF vector — user submits arbitrary URL for processing)

**Articles** (`/api/v1/articles`):
- `GET /api/v1/articles` — List articles with pagination and filters (rate limited 100/min)
- `GET /api/v1/articles/{article_id}` — Get article details

**Search** (`/api/v1/search`):
- `GET /api/v1/search` — Unified search with intent-aware routing (rate limited 100/min)
- `POST /api/v1/search/causal` — Causal reasoning via LLM (rate limited 10/min) — **LLM prompt injection vector**
- `POST /api/v1/search/temporal` — Temporal reasoning via LLM (rate limited 20/min) — **LLM prompt injection vector**
- `POST /api/v1/search/drift` — DRIFT search via LLM (rate limited 20/min) — **LLM prompt injection vector**

**Knowledge Graph** (`/api/v1/graph`):
- `GET /api/v1/graph/entities/{name}` — Entity information
- `GET /api/v1/graph/articles/{article_id}/graph` — Article knowledge graph
- `GET /api/v1/graph/relations` — Relation types for entity
- `GET /api/v1/graph/relations/search` — Search related entities
- `GET /api/v1/graph/visualization` — Graph visualization snapshot
- `POST /api/v1/graph/visualization` — Subgraph extraction
- `GET /api/v1/graph/metrics` — Graph metrics

**Administration** (`/api/v1/admin`):
- `GET /api/v1/admin/authorities` — List source authority ratings
- `PATCH /api/v1/admin/authorities/{host}` — **Modify source authority** (can reconfigure trust levels)
- `GET /api/v1/admin/llm-failures` — LLM failure records
- `GET /api/v1/admin/llm-failures/stats` — LLM failure statistics
- `GET /api/v1/admin/llm-usage` — LLM usage statistics
- `POST /api/v1/admin/articles/deduplicate` — Trigger deduplication
- `GET /api/v1/admin/communities` — List communities
- `GET /api/v1/admin/communities/{community_id}` — Community details
- `POST /api/v1/admin/communities/rebuild` — **Rebuild all communities** (resource-intensive operation)
- `POST /api/v1/admin/communities/reports/generate` — Generate community reports
- `POST /api/v1/admin/communities/{community_id}/report/regenerate` — Regenerate report
- `GET /api/v1/admin/communities/health` — Community health
- `POST /api/v1/admin/communities/health/diagnose` — Diagnose health
- `POST /api/v1/admin/communities/health/repair` — **Repair community health** (modifies data)

### Internal Service Communication
The application communicates with four backend services, all assumed to be on a trusted internal network:
- **PostgreSQL** — Connection via asyncpg with configurable pool settings. No inter-service authentication beyond database credentials.
- **Neo4j** — Bolt protocol connection. No auth details visible in application code (configured via environment).
- **Redis** — Used for caching and rate limiting state. No authentication configuration found.
- **LLM Providers** — External API calls via litellm to aiping.cn, DMXAPI, and Ollama (local). API keys for LLM services are stored in environment variables.

**Trust assumptions:** The application trusts all four database/storage services completely. No mutual TLS, no service mesh authentication, and no network segmentation is enforced at the application level.

### Input Validation Patterns
Input validation follows two patterns:
1. **Pydantic schema validation**: Request bodies are validated via Pydantic models defined in `src/api/schemas/`. This provides automatic type checking and basic validation.
2. **Source URL validation**: URLs submitted for source creation/update are validated in `src/api/endpoints/content/sources.py` via `_validate_source_url()` (lines 26-48) which applies the SSRF and URL validator checks.

**Validation gaps:** The `/api/v1/pipeline/url` endpoint accepts a URL for direct processing but it is unclear whether it applies the same source URL validation as the source creation endpoints. Advanced search endpoints accept free-text queries that are passed directly to LLM models without sanitization, creating prompt injection potential.

### Background Processing
The application uses **APScheduler 3.11.2** for scheduled jobs (`src/modules/scheduler/`). Pipeline processing is triggered either via scheduled cron jobs or manual API triggers. Jobs run with the same privilege level as the application — there is no job-specific permission model. The pipeline trigger endpoint (`POST /api/v1/pipeline/trigger`) allows any authenticated user to initiate resource-intensive crawling and LLM processing operations.

---

## 6. Infrastructure & Operational Security

### Secrets Management
Secrets are managed entirely through **environment variables** loaded via pydantic-settings (`src/config/settings.py` and `src/config/subconfigs.py`). The configuration hierarchy is: Environment variables > `.env` file > TOML config > defaults.

**Key secrets in the environment:**
- `WEAVER__API__API_KEY` — Application API key (generated via `secrets.token_urlsafe(32)` if not set)
- `WEAVER__CORE__DB__POSTGRES__DSN` — PostgreSQL connection string
- `WEAVER__CORE__DB__NEO4J__URI` / `USERNAME` / `PASSWORD` — Neo4j credentials
- `WEAVER__CORE__DB__REDIS__URL` — Redis connection URL
- `WEAVER__CORE__LLM__API_KEY` — LLM provider API keys
- `WEAVER__SECURITY__HMAC_KEY` — HMAC signing key

**Security concern:** The `.env` file exists in the project root but is properly gitignored. However, `config/settings.toml` and `config/llm.toml` are also gitignored and contain operational configuration. The `.env.example` file is tracked and reveals the expected secret names and some default values, providing attackers with a blueprint for what environment variables to target.

### Configuration Security
Environment separation is managed via the `WEAVER__ENVIRONMENT` variable (defaults to "development"). In production mode, the application validates that weak/default credentials are not in use (`src/config/settings.py`, lines 158-178) and warns about insecure configurations.

**Security headers from application middleware** (`src/main.py`, SecurityHeadersMiddleware, lines 258-279):
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` — HSTS enabled for 1 year
- `X-Content-Type-Options: nosniff` — Prevents MIME sniffing
- `X-Frame-Options: DENY` — Prevents clickjacking
- `X-XSS-Protection: 1; mode=block` — Legacy XSS protection

**Note:** These headers are set by the application middleware, not by infrastructure (Nginx/CDN). No infrastructure-level configuration files (Nginx, Kubernetes Ingress, CDN settings) were found in the tracked codebase for additional header enforcement.

### External Dependencies
- **litellm 1.83.0** — Multi-provider LLM API client; security depends on litellm's handling of API keys and request routing
- **Crawl4AI 0.8.6** — Headless browser crawling with stealth mode; represents the SSRF bypass vector
- **httpx** — HTTP client used for fetching; applies SSRF validation on the primary path
- **Neo4j Python Driver** — Graph database client; uses parameterized queries
- **asyncpg** — PostgreSQL async driver; uses parameterized queries via SQLAlchemy

### Monitoring & Logging
- **OpenTelemetry** tracing with OTLP endpoint support (`src/core/observability/`)
- **Prometheus Client** metrics exposed at `/metrics` (unauthenticated)
- **Structured logging** with loguru including correlation IDs
- **Log sanitization** via `src/core/utils/sanitize.py` — masks passwords, API keys, tokens, and connection strings in log output using regex-based pattern detection
- **Circuit breaker pattern** (pybreaker) for resilience against external service failures

**Security concern:** The `/metrics` endpoint exposes Prometheus metrics without authentication, potentially revealing application performance data, request rates, error rates, and internal service health to unauthenticated attackers.

---

## 7. Overall Codebase Indexing

The Weaver codebase is organized as a Python project with a `src/` layout following clean architecture principles. The root directory contains standard Python project files: `pyproject.toml` for dependency management (using UV package manager with `uv.lock`), `.python-version` specifying Python 3.12, and `alembic.ini` for database migration configuration. The `src/` directory is the primary application codebase, organized into three main layers: `src/api/` (FastAPI routers, middleware, and request/response schemas), `src/core/` (infrastructure including database connections, LLM clients, NLP processing, security utilities, and observability), and `src/modules/` (domain-specific business logic for ingestion, knowledge graph operations, processing, storage, and analytics). Configuration files reside in `config/` (gitignored `settings.toml` and `llm.toml`, plus tracked files like `pipeline.toml`). The `docker/` directory contains Dockerfile and docker-compose configurations for the multi-service deployment (PostgreSQL, Neo4j, Redis, application). The `tests/` directory mirrors the `src/` structure with unit and integration tests. The `monitoring/` directory contains observability configurations. Build and development tooling includes `.pre-commit-config.yaml`, `pytest.ini`, and a `scripts/` directory for operational scripts. The `data/` and `temp/` directories are gitignored and contain runtime data. Security-relevant code is distributed across `src/api/middleware/` (authentication, rate limiting), `src/core/security/` (SSRF protection, URL validation, crypto), `src/core/db/` (database connections and safe query utilities), and `src/core/utils/` (log sanitization). The modular structure makes security-relevant components discoverable but requires examining multiple layers to understand complete security flows.

---

## 8. Critical File Paths

### Configuration
- `pyproject.toml` — Dependency declarations, Python version, build configuration
- `.env.example` — Template revealing expected environment variable names and defaults
- `config/pipeline.toml` — Processing pipeline configuration (tracked)
- `alembic.ini` — Database migration configuration
- `docker/Dockerfile` — Container image definition
- `docker/docker-compose.yml` — Multi-service deployment (PostgreSQL, Neo4j, Redis, app)
- `.gitignore` — Reveals gitignored files containing secrets (config/settings.toml, config/llm.toml, .env)

### Authentication & Authorization
- `src/api/middleware/auth.py` — API key authentication implementation (verify_api_key dependency, X-API-Key header, secrets.compare_digest)
- `src/config/settings.py` — Settings loading with production security validation (lines 158-178)
- `src/config/subconfigs.py` — API key configuration with minimum length enforcement (32 chars), key generation

### API & Routing
- `src/main.py` — Application entry point, middleware registration (CORS, security headers, request size limit), health/metrics endpoints
- `src/api/router.py` — Central router registration with `/api/v1` prefix
- `src/api/endpoints/content/sources.py` — Source CRUD endpoints with URL validation (SSRF-relevant)
- `src/api/endpoints/content/pipeline.py` — Pipeline trigger and URL processing endpoints (SSRF-relevant)
- `src/api/endpoints/content/articles.py` — Article listing and detail endpoints
- `src/api/endpoints/content/search.py` — Search endpoints including LLM-powered causal/temporal/DRIFT search (prompt injection-relevant)
- `src/api/endpoints/graph/graph.py` — Knowledge graph entity and relation endpoints
- `src/api/endpoints/graph/graph_metrics.py` — Graph metrics endpoints
- `src/api/endpoints/graph/graph_visualization.py` — Graph visualization endpoints
- `src/api/endpoints/admin/admin.py` — Administrative endpoints (authorities, LLM failures, usage, deduplication)
- `src/api/endpoints/communities.py` — Community management endpoints (rebuild, reports, health)
- `src/api/middleware/rate_limit.py` — Rate limiting middleware (slowapi, 100/min default)

### Data Models & DB Interaction
- `src/core/db/models.py` — SQLAlchemy ORM models (Article, Source, etc.)
- `src/core/db/postgres.py` — PostgreSQL async connection setup (no SSL enforcement, lines 61-72)
- `src/core/db/neo4j.py` — Neo4j connection setup (no SSL enforcement, line 30)
- `src/core/db/duckdb_pool.py` — DuckDB connection pool (local file-based)
- `src/core/db/safe_query.py` — SQL identifier validation utilities
- `src/modules/migration/adapters/postgres_target.py` — PostgreSQL migration adapter with SQL injection risk (lines 89, 116)
- `src/modules/migration/adapters/duckdb_target.py` — DuckDB migration adapter with SQL injection risk (lines 115, 175)
- `src/modules/storage/postgres/` — PostgreSQL data access layer
- `src/modules/storage/neo4j/` — Neo4j data access layer (uses parameterized queries)

### Dependency Manifests
- `pyproject.toml` — All Python dependencies with version constraints
- `uv.lock` — Locked dependency versions

### Sensitive Data & Secrets Handling
- `src/core/security/crypto/signing.py` — HMAC-SHA256 data integrity signing
- `src/core/utils/sanitize.py` — Log sanitization (masks passwords, API keys, tokens, DSNs)
- `src/core/nlp/spacy_manager.py` — spaCy model management with subprocess.run (command injection potential, line 166) and path traversal risk (lines 111, 145, 146)

### Middleware & Input Validation
- `src/api/middleware/auth.py` — API key authentication middleware
- `src/api/middleware/rate_limit.py` — Rate limiting middleware
- `src/core/security/validation/ssrf.py` — SSRF protection (RFC 1918, cloud metadata, IPv6)
- `src/core/security/validation/validator.py` — Multi-layered URL validation (SSRF + URLhaus + PhishTank + heuristics)
- `src/api/schemas/response.py` — API response schemas (Pydantic)
- `src/api/schemas/llm_usage.py` — LLM usage schema definitions

### Logging & Monitoring
- `src/core/observability/` — OpenTelemetry tracing, logging, metrics
- `src/core/utils/sanitize.py` — Sensitive data masking in logs

### Infrastructure & Deployment
- `docker/Dockerfile` — Container build with Python 3.12-slim, UV, spaCy, Playwright
- `docker/docker-compose.yml` — Multi-service orchestration
- `monitoring/` — Observability configurations

---

## 9. XSS Sinks and Render Contexts

**Network Surface Assessment:** Weaver is a **backend REST API** with no HTML rendering, no template engine, and no server-side rendered web pages. The application returns JSON responses exclusively via FastAPI's JSON serialization. As such, **traditional XSS sinks (innerHTML, document.write, etc.) are not present** in the network-accessible attack surface.

**No XSS sinks were found in the network-accessible codebase.** The application does not:
- Serve HTML templates
- Use any template engines (Jinja2, Mako, etc.)
- Include any client-side JavaScript framework
- Render user-controlled data in HTML contexts

**Secondary consideration:** While the application itself does not render HTML, the API responses containing user-controlled content (article titles, source names, entity names from the knowledge graph) could introduce stored XSS if downstream consumers render this data without sanitization. This is a consumer-side responsibility but worth noting for defense-in-depth testing.

---

## 10. SSRF Sinks

### Critical SSRF Sink: Crawl4AI Browser-Based Fetcher (No SSRF Validation)

**File:** `src/modules/ingestion/fetching/crawl4ai_fetcher.py`, line 95
**Code Pattern:** `await self._crawler.arun(url)` — directly passes user-controlled URL to browser without SSRF validation
**User Input Flow:** `POST /api/v1/sources` (source URL) → `POST /api/v1/pipeline/trigger` → SmartFetcher → Crawl4AIFetcher fallback → `arun(url)`
**SSRF Protection Applied:** ❌ **NONE** — Crawl4AIFetcher bypasses the SSRF validation applied in the primary SmartFetcher path
**Trigger Conditions:** Activated when SmartFetcher falls back to browser rendering (SPA detection, short content < 500 chars, force_browser=True)
**Network Accessible:** ✅ Yes — reachable via source creation/update and pipeline trigger endpoints
**Impact:** Full SSRF bypass allowing internal network scanning, cloud metadata access (AWS/GCP/Azure 169.254.169.254), and internal service interaction via headless browser

### SSRF Sink: Source URL Configuration (Protected)

**File:** `src/api/endpoints/content/sources.py`, lines 59, 98, 227, 276
**HTTP Client Chain:** SmartFetcher → HttpxFetcher → httpx
**User Input Control:** `SourceCreateRequest.url` and `SourceUpdateRequest.url`
**SSRF Protection Applied:** ✅ Applied via `_validate_source_url()` (lines 26-48) which invokes URLValidator → SSRFChecker
**Network Accessible:** ✅ Yes — POST `/api/v1/sources` and PUT `/api/v1/sources/{source_id}`
**Protection Level:** GOOD — but bypassable via Crawl4AI fallback

### SSRF Sink: Direct URL Pipeline Processing

**File:** `src/api/endpoints/content/pipeline.py`
**HTTP Client Chain:** POST `/api/v1/pipeline/url` → Pipeline processing → SmartFetcher → httpx / Crawl4AI
**User Input Control:** `url` parameter in request body (required)
**SSRF Protection Applied:** ⚠️ Partially — depends on fetcher path taken (httpx path protected, Crawl4AI path unprotected)
**Network Accessible:** ✅ Yes — direct endpoint accepting arbitrary URLs for processing

### SSRF Sink: RSS/Feed Fetching

**Files:** `src/modules/ingestion/parsing/rss_parser.py` (line 62), `src/modules/ingestion/parsing/newsnow_parser.py` (line 44)
**HTTP Client Chain:** SmartFetcher → HttpxFetcher → httpx
**User Input Control:** URLs from source configuration (user-controlled via source CRUD)
**SSRF Protection Applied:** ✅ Applied through URLValidator in SmartFetcher
**Network Accessible:** ✅ Indirect — triggered via scheduler or pipeline trigger
**Protection Level:** GOOD on primary path

### SSRF Sink: LLM API Base URL Configuration

**File:** `src/core/llm/caller.py`, lines 90, 173, 261, 344
**HTTP Client:** litellm → OpenAI-compatible API
**User Input Control:** `api_base` URLs from configuration (environment-controlled, not directly user-controllable via API)
**SSRF Protection Applied:** ❌ No URL validation on LLM API base URLs
**Network Accessible:** ⚠️ Indirect — not directly controllable via API requests, but if configuration is compromised via `/api/v1/config` disclosure
**Protection Level:** Configuration-dependent — relies on environment security

### SSRF Protection Analysis

The application's SSRF protection in `src/core/security/validation/ssrf.py` is comprehensive on paper, blocking:
- RFC 1918 private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Cloud metadata endpoints (169.254.169.254, metadata.google.internal, 100.100.100.200)
- Loopback (127.0.0.0/8, ::1/128)
- Link-local (169.254.0.0/16, fe80::/10)
- Multicast and IPv6 unique local (fc00::/7)
- DNS resolution verification to detect IP-based bypass attempts

**However, the Crawl4AI fetcher completely bypasses this protection**, making it the primary SSRF exploitation target. An attacker can craft source URLs that trigger the browser fallback to reach internal services.
