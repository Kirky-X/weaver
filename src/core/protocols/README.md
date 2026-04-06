# Core Protocols Module

This module defines Python Protocol interfaces for the weaver project's dependency injection and database abstraction layers.

## Design Philosophy

- **Explicit Interface Declarations**: All implementations must declare which Protocol they implement
- **禁止隐式实现 (No Implicit Implementation)**: Duck typing is discouraged; use Protocol for type safety
- **Runtime Verification**: Protocol compliance can be validated at startup

## Module Structure

```
src/core/protocols/
├── __init__.py          # Re-exports all protocols and utilities
├── pools.py             # Database and cache pool protocols
├── repositories.py      # Repository protocols for data access
└── validation.py        # Runtime validation utilities
```

## Available Protocols

### Pool Protocols (`pools.py`)

| Protocol         | Purpose                    | Key Methods                                                       |
| ---------------- | -------------------------- | ----------------------------------------------------------------- |
| `RelationalPool` | SQL database connections   | `startup()`, `shutdown()`, `session()`, `engine`                  |
| `GraphPool`      | Graph database connections | `startup()`, `shutdown()`, `execute_query()`, `session_context()` |
| `CachePool`      | Cache operations           | `startup()`, `shutdown()`, `get()`, `set()`, `delete()`           |

### Repository Protocols (`repositories.py`)

| Protocol            | Purpose                      | Key Methods                                                             |
| ------------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `EntityRepository`  | Entity CRUD operations       | `find_entity()`, `merge_entity()`, `add_alias()`                        |
| `VectorRepository`  | Vector similarity operations | `find_similar()`, `find_similar_entities()`, `upsert_article_vectors()` |
| `ArticleRepository` | Article data access          | `get_by_id()`, `create()`, `update()`                                   |

## Usage Examples

### Declaring Protocol Implementation

Use a docstring to declare which Protocol a class implements:

```python
from core.protocols import RelationalPool

class PostgresPool:
    """PostgreSQL connection pool.

    Implements: RelationalPool
    """

    async def startup(self) -> None:
        # Implementation...

    async def shutdown(self) -> None:
        # Implementation...

    @contextmanager
    def session(self):
        # Implementation...
```

### Type Annotations with Protocols

Use Protocol types in function signatures and class attributes:

```python
from core.protocols import RelationalPool, VectorRepository

class MyService:
    def __init__(self, pool: RelationalPool, vector_repo: VectorRepository):
        self._pool = pool
        self._vector_repo = vector_repo
```

### Runtime Validation

Validate Protocol compliance at startup:

```python
from core.protocols import assert_implements, RelationalPool, GraphPool

def validate_implementations():
    """Call during application startup."""
    from modules.storage.postgres.pool import PostgresPool
    from modules.storage.neo4j.pool import Neo4jPool

    assert_implements(PostgresPool, RelationalPool)
    assert_implements(Neo4jPool, GraphPool)
```

### Getting Protocol Methods

Inspect which methods a Protocol requires:

```python
from core.protocols import get_protocol_methods, RelationalPool

methods = get_protocol_methods(RelationalPool)
# Returns: {'startup', 'shutdown', 'session', 'engine', ...}
```

## Container Integration

The DI container returns Protocol types from its accessors:

```python
class Container:
    def relational_pool(self) -> RelationalPool:
        """Returns the configured SQL database pool."""

    def graph_pool(self) -> GraphPool | None:
        """Returns the configured graph database pool, if available."""

    def cache_client(self) -> CachePool:
        """Returns the configured cache client."""

    def vector_repo(self) -> VectorRepository:
        """Returns the configured vector repository."""
```

## QueryBuilder Pattern

The `VectorRepository` uses the QueryBuilder pattern for database-agnostic operations:

```python
from core.db.query_builders import VectorQueryBuilder, create_vector_query_builder

# Factory creates the appropriate builder
query_builder = create_vector_query_builder("postgres")  # or "duckdb"

# Inject into repository
repo = VectorRepo(pool=pool, query_builder=query_builder)
```

## Implementation Checklist

When adding a new implementation:

- [ ] Add "Implements: ProtocolName" to the class docstring
- [ ] Ensure all Protocol methods are implemented
- [ ] Use Protocol type in constructor parameters (not concrete type)
- [ ] Add runtime validation test
- [ ] Update Container accessor return type to Protocol

## Testing

Run Protocol validation tests:

```bash
pytest tests/unit/core/protocols/
```

## References

- [PEP 544: Protocols](https://peps.python.org/pep-0544/)
- [Python typing documentation](https://docs.python.org/3/library/typing.html#typing.Protocol)
