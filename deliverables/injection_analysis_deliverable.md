# Injection Analysis Report (SQLi & Command Injection)

## 1. Executive Summary

- **Analysis Status:** Complete
- **Key Outcome:** Three high-confidence injection vulnerabilities were identified and confirmed through comprehensive source-to-sink data flow analysis. All findings have been passed to the exploitation phase via the machine-readable queue at `deliverables/injection_exploitation_queue.json`.
- **Purpose of this Document:** This report provides the strategic context, dominant patterns, and environmental intelligence necessary to effectively exploit the vulnerabilities listed in the queue. It is intended to be read alongside the JSON deliverable.

## 2. Vulnerabilities Identified

| ID | Type | Endpoint | Severity | Externally Exploitable |
|---|------|----------|----------|------------------------|
| INJ-VULN-01 | SQL Injection | POST /api/v1/migration/relational (PostgreSQL) | **HIGH** | ⚠️ **UNCLEAR** - API not in main router |
| INJ-VULN-02 | SQL Injection | POST /api/v1/migration/relational (DuckDB) | **HIGH** | ⚠️ **UNCLEAR** - API not in main router |
| INJ-VULN-03 | Cypher Injection | GET /api/v1/graph/relations/search | **MEDIUM** | ✅ **YES** - Requires API key |

**Critical Note on Network Accessibility:**
- The migration API endpoints (`INJ-VULN-01`, `INJ-VULN-02`) exist in the codebase but are **NOT registered** with the main FastAPI application router. These vulnerabilities may only be exploitable if:
  1. The application is configured with a custom router that includes the migration endpoints
  2. The endpoints are exposed through a separate admin interface
  3. The application is started with a non-default configuration

- The Cypher Injection vulnerability (`INJ-VULN-03`) is confirmed network-accessible through the main API router but requires valid API key authentication.

## 3. Dominant Vulnerability Patterns

### Pattern 1: Direct String Interpolation of SQL Identifiers

**Description:** User input is directly interpolated into SQL queries using Python f-strings for table names (SQL identifiers), which cannot be parameterized. The code lacks any validation or sanitization before interpolation.

**Implication:** Attackers can inject arbitrary SQL by breaking out of double-quoted identifiers. This allows for:
- Data exfiltration through UNION-based injection
- Database schema modification (DROP TABLE, ALTER TABLE)
- Bypass of application logic (WHERE clause manipulation)

**Representative:** `INJ-VULN-01` (PostgreSQL migration endpoint)

**Code Example:**
```python
# VULNERABLE - postgres_target.py:89
text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{schema.table}"')
# If table = "users\"; DROP TABLE users; --"
# Results in: CREATE INDEX IF NOT EXISTS "idx" ON "users"; DROP TABLE users; --"
```

### Pattern 2: Inconsistent Validation Across Database Adapters

**Description:** The codebase has proper validation functions (`validate_sql_identifier()`, `validate_edge_type()`) in `src/core/db/safe_query.py` that are used by Neo4j and Ladybug adapters but NOT by PostgreSQL and DuckDB adapters.

**Implication:** This inconsistency creates a false sense of security. The presence of validation in some parts of the codebase suggests the developers were aware of the risk but failed to apply it consistently.

**Representative:** `INJ-VULN-01` and `INJ-VULN-02` (both lack validation used elsewhere)

**Evidence:**
- Neo4j adapter uses: `validate_edge_type()` from `safe_query.py`
- Ladybug adapter uses: `validate_sql_identifier()` from `safe_query.py`
- PostgreSQL adapter: NO validation
- DuckDB adapter: NO validation

### Pattern 3: Comma-Separated Input Without Individual Validation

**Description:** When input is split by comma, individual values are not validated. The code only strips whitespace but does not apply security validation to each component.

**Implication:** Attackers can inject malicious payloads into any comma-separated value. The split operation creates multiple injection points from a single input parameter.

**Representative:** `INJ-VULN-03` (Cypher Injection)

**Code Example:**
```python
# VULNERABLE - graph.py:244-245
types_list = [t.strip() for t in relation_types.split(",") if t.strip()]
# If relation_types = "RELATED_TO' OR '1'='1"
# Results in: ['RELATED_TO\' OR \'1\'=\'1']
# Then interpolated into: type(r) = 'RELATED_TO' OR '1'='1'
```

## 4. Strategic Intelligence for Exploitation

### 4.1 Authentication Requirements

**API Key Required:**
All confirmed vulnerabilities require valid API key authentication via the `verify_api_key` dependency.

**Implication:**
- Exploitation requires obtaining a valid API key first
- Default API keys may be present in configuration files
- API keys are typically passed via `X-API-Key` header or `api_key` query parameter

**Recommendation:**
- Attempt to enumerate default or leaked API keys
- Check for weak API key generation patterns
- Test if authentication can be bypassed

### 4.2 Database Technologies Identified

**PostgreSQL (INJ-VULN-01):**
- Uses SQLAlchemy with `text()` for raw SQL execution
- Double-quote identifier escaping (insufficient alone)
- PostgreSQL-specific functions available: `pg_sleep()`, `version()`, `current_database()`

**DuckDB (INJ-VULN-02):**
- Uses SQLAlchemy with `text()` for raw SQL execution
- Double-quote identifier escaping (insufficient alone)
- DuckDB-specific functions available: `current_database()`, `version()`

**Neo4j (INJ-VULN-03):**
- Uses Cypher query language
- Single-quote string escaping (insufficient alone)
- Neo4j-specific functions available: `count()`, `exists()`

### 4.3 Injection Point Contexts

**SQL Injection Contexts (PostgreSQL/DuckDB):**
1. **CREATE TABLE statements** - `postgres_target.py:78`, `duckdb_target.py:88`
2. **CREATE INDEX statements** - `postgres_target.py:89`
3. **ALTER TABLE statements** - `postgres_target.py:116`, `duckdb_target.py:115`
4. **INSERT statements** - `postgres_target.py:146`, `duckdb_target.py:140`
5. **SELECT statements** - `postgres_source.py:162`, `duckdb_source.py:138`
6. **TRUNCATE statements** - `postgres_target.py:195`
7. **DELETE statements** - `duckdb_target.py:194`

**Cypher Injection Context (Neo4j):**
1. **WHERE clause** - `graph_query_builders.py:367`
   - Pattern: `type(r) = '{relation_type}'`
   - Allows injection into relationship type matching

### 4.4 Error Handling and Disclosure

**Verbose Error Messages:**
The application may return detailed error messages including:
- SQL query syntax errors
- Table/column not found errors
- Type mismatch errors

**Implication:**
- Error-based injection techniques may be viable
- Database schema can be inferred from error messages
- Injection success/failure can be determined through error responses

### 4.5 WAF/Filtering Considerations

**No WAF Detected:**
The reconnaissance did not identify a Web Application Firewall protecting these endpoints.

**Implication:**
- Standard injection payloads can be used without obfuscation
- No need for advanced bypass techniques
- Direct exploitation should be possible

## 5. Vectors Analyzed and Confirmed Secure

The following injection types were investigated and confirmed to have NO network-accessible attack surface:

| Injection Type | Finding | Network Accessible? |
|---|---|---|
| **Command Injection** | One subprocess call found in `spacy_manager.py:166` but only during application startup, not from HTTP requests | ❌ **NO** |
| **LFI/RFI** | Dynamic file operations exist in migration module but router is not registered with FastAPI app | ❌ **NO** |
| **SSTI** | No template engines (Jinja2, Mako, etc.) used in network-accessible code. Python `.format()` only used with database-derived data | ❌ **NO** |
| **Insecure Deserialization** | All YAML uses `yaml.safe_load()`, pickle uses `RestrictedUnpickler` with HMAC verification, no `json.loads` with `object_hook` | ❌ **NO** |

**Detailed Analysis:**

**Command Injection:**
- The only subprocess execution in production code is `spacy_manager.py:166`
- Called ONLY during application startup via `_ensure_spacy_models()` in `main.py:41-60`
- Configuration comes from `config/settings.toml` and environment variables, NOT user input
- No API endpoints trigger command execution

**LFI/RFI:**
- Dynamic file operations exist in `mapping_registry.py:95,299` for `mapping_file` parameter
- However, the migration API router (`/repos/weaver/src/modules/migration/api/routes.py`) is NOT included in the main FastAPI application
- Network-accessible endpoints use only hardcoded or configuration-based paths

**SSTI:**
- No traditional template engines (Jinja2, Mako, Django templates) imported or used in API endpoints
- Python `.format()` used only in:
  - `detector.py:500` - community title generation (database data only)
  - `report_generator.py:381` - LLM prompt construction (database data only)
- No path from user input to template rendering operations

**Insecure Deserialization:**
- All YAML parsing uses `yaml.safe_load()` (not `yaml.load`)
- Pickle operations use custom `RestrictedUnpickler` class that whitelists only safe built-in types
- All `json.loads()` calls use default parsing (no `object_hook`)
- Migration API with YAML parsing is not network-accessible

## 6. Analysis Constraints and Blind Spots

### 6.1 Network Accessibility Uncertainty

**Migration API Router Status:**
The migration API endpoints (`POST /api/v1/migration/relational` and `POST /api/v1/migration/graph`) exist in the codebase but are NOT included in the main API router at `/repos/weaver/src/api/router.py`.

**Possible Explanations:**
1. **Disabled by Default:** The migration API may be an experimental or admin-only feature that is not enabled in standard deployments
2. **Separate Admin Interface:** There may be a separate admin application or service that includes these endpoints
3. **CLI-Only Usage:** The migration functionality may be intended for CLI use only (via `/repos/weaver/src/modules/migration/cli/commands.py`)
4. **Configuration-Dependent:** The router may be conditionally included based on configuration settings not visible in static analysis

**Implication for Exploitation:**
- `INJ-VULN-01` and `INJ-VULN-02` may NOT be exploitable via the main web application
- Testing should first verify whether the migration endpoints are accessible
- If accessible, these are HIGH severity vulnerabilities
- If not accessible, these represent potential security risks for alternative deployment scenarios

### 6.2 Authentication Bypass

**API Key Validation:**
All network-accessible endpoints require API key authentication via the `verify_api_key` dependency. The implementation of this validation was not analyzed in detail.

**Potential Concerns:**
- Default or weak API keys may be present
- API key validation may have bypass vulnerabilities
- API key leakage may have occurred in logs or error messages

**Recommendation:**
- Verify API key validation strength before attempting exploitation
- Attempt to enumerate default or leaked API keys
- Test for authentication bypass vulnerabilities

### 6.3 Database Schema Unknown

**Schema Information:**
The exact database schema (table names, column names, relationships) is not known from static analysis alone.

**Implication:**
- Exploitation may require schema enumeration through injection
- Error messages may reveal schema information
- Database discovery queries will be necessary

### 6.4 Configuration Variability

**Deployment Configurations:**
The application may be deployed with different configurations that:
- Enable or disable certain endpoints
- Use different database backends
- Implement additional security controls
- Route requests through proxy services

**Implication:**
- Vulnerability exploitability may vary across deployments
- Testing should verify the actual deployment configuration

## 7. Proof of Concept Payloads (Hold for Exploitation Phase)

**DO NOT EXECUTE during analysis phase. These are reference payloads for the exploitation phase.**

### SQLi Payloads (PostgreSQL/DuckDB)

**Identifier Escape:**
```
users"; DROP TABLE secrets; --
```

**Union-Based:**
```
users" UNION SELECT NULL,NULL,NULL --
```

**Boolean-Based:**
```
users" AND 1=1 --
users" AND 1=2 --
```

**Time-Based (PostgreSQL):**
```
users"; SELECT pg_sleep(5) --
```

**Error-Based:**
```
users" CAST(version() AS INT) --
```

### Cypher Injection Payloads (Neo4j)

**Boolean-Based:**
```
RELATED_TO' OR '1'='1
```

**Union-Based:**
```
RELATED_TO' UNION MATCH (n) RETURN n --
```

**Injection into Relationship Type:**
```
RELATED_TO' RETURN 1 AS a UNION MATCH (n) RETURN n.name --
```

---

**END OF INJECTION ANALYSIS DELIVERABLE**
