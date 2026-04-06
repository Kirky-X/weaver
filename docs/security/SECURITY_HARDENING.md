# Security Hardening Documentation

This document describes the security measures implemented in the Weaver application.

## Overview

Weaver implements defense-in-depth security practices to protect against common web vulnerabilities, with particular focus on injection attacks and data integrity.

## Injection Prevention

### SQL Injection Protection

All SQL queries use **parameterized queries** via the QueryBuilder pattern:

```python
# ✅ Safe: Parameterized query
result = await pool.execute_query(
    "SELECT * FROM nodes WHERE label = $1",
    {"1": label}
)

# ❌ Unsafe: String concatenation (NEVER do this)
result = await pool.execute_query(
    f"SELECT * FROM nodes WHERE label = '{label}'"
)
```

**Implementation:**

- `src/core/db/query_builders.py` - VectorQueryBuilder for parameterized vector operations
- `src/core/db/safe_query.py` - Validation functions for SQL identifiers

### Cypher Injection Protection

Neo4j Cypher queries also use parameterized syntax:

```python
# ✅ Safe: Parameterized Cypher
result = await pool.execute_query(
    """
    MATCH (n)
    WHERE $label IN labels(n)
    RETURN n
    """,
    {"label": label}
)

# ❌ Unsafe: String interpolation
result = await pool.execute_query(
    f"MATCH (n:`{label}`) RETURN n"
)
```

**Implementation:**

- `src/core/db/safe_query.py` - `validate_neo4j_label()`, `validate_edge_type()`
- All graph database adapters use parameterized queries

### Input Validation

User-provided identifiers are validated before use:

| Input Type     | Validation Function         | Pattern                                              |
| -------------- | --------------------------- | ---------------------------------------------------- |
| SQL identifier | `validate_sql_identifier()` | `^[a-zA-Z_][a-zA-Z0-9_]*$`                           |
| Neo4j label    | `validate_neo4j_label()`    | `^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$` |
| Edge type      | `validate_edge_type()`      | `^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$`       |
| UUID           | `validate_uuid()`           | Standard UUID format                                 |

## Data Integrity

### Signed JSON Serialization

BM25 index files use signed JSON to prevent tampering:

```python
from core.security.signing import save_signed_json, load_signed_json, SigningKey

# Save with signature
key = SigningKey.from_env("INDEX_SIGNING_KEY")
save_signed_json(index_data, "index.json", key)

# Load with verification (raises IntegrityError if tampered)
data = load_signed_json("index.json", key)
```

**Security Benefits:**

- HMAC signature prevents undetected modification
- JSON format eliminates code execution risk from pickle
- Automatic detection of tampering attempts

### Migration from Pickle

The BM25 retriever previously used `pickle.load()` which is vulnerable to malicious payloads:

```python
# ❌ Old: Vulnerable to code execution
with open("index.pkl", "rb") as f:
    data = pickle.load(f)

# ✅ New: Safe JSON with signature verification
data = load_signed_json("index.json", key)
```

## Architecture Security

### Service Layer Pattern

Cross-module calls go through service interfaces, not internal methods:

```python
# ❌ Bad: Direct internal method access
result = await pipeline._phase3_per_article(state)

# ✅ Good: Public service interface
result = await pipeline_service.run_phase3_per_article(article_id)
```

**Benefits:**

- Clear API contract
- Easier to audit access patterns
- Enables access control at service boundary

### Dependency Injection

API endpoints use FastAPI dependency injection instead of global state:

```python
# ❌ Bad: Global variable
_pg_pool: AsyncConnection | None = None

# ✅ Good: Dependency injection
@router.get("/data")
async def get_data(container: Container = Depends(get_container)):
    pool = container.relational_pool()
```

**Benefits:**

- No hidden mutable state
- Testable with mock dependencies
- Clear data flow

### Background Task Tracking

Background tasks are registered for observability:

```python
# ❌ Bad: Fire-and-forget
asyncio.create_task(process_url(url))

# ✅ Good: Tracked task
task = asyncio.create_task(process_url(url))
await task_registry.register(task_id, task, metadata={"url": url})
```

## Startup Security Audit

The application runs security checks at startup:

```python
from core.security.audit import run_security_audit

report = run_security_audit("src")
if not report.passed:
    logger.warning("Security issues detected", issues=report.results)
```

**Checks performed:**

- Environment variable security configuration
- Code pattern scanning for injection risks
- Pickle deserialization detection

## Configuration

### Required Environment Variables

| Variable            | Purpose             | Risk if Missing                    |
| ------------------- | ------------------- | ---------------------------------- |
| `INDEX_SIGNING_KEY` | BM25 index HMAC key | Index tampering undetected         |
| `SECRET_KEY`        | Application secret  | Session forgery risk               |
| `ENVIRONMENT`       | Deployment mode     | Development settings in production |

### Security Headers

FastAPI includes security middleware:

- CORS configuration via environment
- Rate limiting via `slowapi`
- SSRF protection in `core.security.ssrf`

## Testing

Security tests are in `tests/unit/modules/migration/adapters/`:

- `test_ladybug_source.py` - SQL injection prevention
- `test_neo4j_source.py` - Cypher injection prevention

Run security scan:

```bash
bandit -r src/
```

## Incident Response

If a security vulnerability is discovered:

1. **Do not commit** the fix to a public branch
2. Report to security team
3. Assess blast radius using `gitnexus_impact()`
4. Apply fix in security patch release
5. Rotate any exposed secrets

## References

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- Neo4j Cypher Injection: https://neo4j.com/developer-blog/cypher-injection/
- Python Security: https://python.readthedocs.io/en/stable/library/security_warnings.html
