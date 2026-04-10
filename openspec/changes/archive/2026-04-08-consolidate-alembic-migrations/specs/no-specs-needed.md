# No Specs Required

This change is an internal refactoring that consolidates Alembic migration files.

**No new capabilities** are being introduced.
**No existing capabilities** are being modified at the requirement level.

The final database schema remains identical:
- 13 tables (articles, article_vectors, entity_vectors, source_authorities, llm_failures, sources, pending_sync, relation_types, relation_type_aliases, unknown_relation_types, llm_usage_raw, llm_usage_hourly, prompt_templates)
- 4 custom ENUM types (category_type, persist_status, emotion_type, vector_type)
- Vector indexes (HNSW)

All existing APIs and data structures are unchanged.