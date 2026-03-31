# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Modules package - Business logic modules for the weaver application.

This package contains all business logic modules organized by domain:

- ingestion: Content ingestion (crawling, fetching, deduplication, parsing, scheduling)
- processing: Data processing (pipeline, nlp, nodes)
- knowledge: Knowledge graph and search (graph, search, community, metrics)
- analytics: LLM analytics (usage tracking, failure analysis)
- storage: Database repositories (PostgreSQL, Neo4j)
- scheduler: Background job scheduling
- management: CLI commands and management utilities

Note: Import specific modules to avoid circular imports:
    from modules.ingestion import Crawler, Deduplicator
    from modules.storage import ArticleRepo
    from modules.processing.pipeline.graph import Pipeline
    from modules.knowledge.graph import Neo4jWriter
    from modules.knowledge.search import GlobalSearchEngine
"""

__all__ = []
