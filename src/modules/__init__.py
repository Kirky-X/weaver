"""Modules package - Business logic modules for the weaver application.

This package contains all business logic modules:
- fetcher: Web content fetching (Playwright, HTTPX)
- collector: Web crawling and content collection
- graph_store: Neo4j graph database operations
- nlp: Natural language processing utilities
- storage: Database repositories (PostgreSQL, Neo4j)
- pipeline: Data processing pipeline with LangGraph
- scheduler: Background job scheduling
- source: RSS feed and data source management
- search: Local and global search engines
- community: Community detection and reporting

Note: Import specific modules to avoid circular imports:
    from modules.fetcher import SmartFetcher
    from modules.storage import ArticleRepo
    from modules.pipeline.graph import Pipeline
"""

__all__ = []
