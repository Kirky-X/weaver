"""Test data factories for creating test objects."""

import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Any


class ArticleRawFactory:
    """Factory for creating ArticleRaw test objects."""

    @staticmethod
    def create(
        url: str | None = None,
        title: str | None = None,
        body: str | None = None,
        source: str | None = None,
        source_host: str | None = None,
        publish_time: datetime | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create an ArticleRaw-like dictionary."""
        return {
            "url": url or f"https://example.com/article/{uuid.uuid4()}",
            "title": title or f"Test Article {random.randint(1000, 9999)}",
            "body": body or "This is a test article body with some content.",
            "source": source or "Test Source",
            "source_host": source_host or "example.com",
            "publish_time": publish_time or datetime.now(timezone.utc),
            **kwargs,
        }

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[dict[str, Any]]:
        """Create multiple ArticleRaw objects."""
        return [ArticleRawFactory.create(**kwargs) for _ in range(count)]


class NewsItemFactory:
    """Factory for creating NewsItem test objects."""

    @staticmethod
    def create(
        url: str | None = None,
        title: str | None = None,
        description: str | None = None,
        source: str | None = None,
        source_host: str | None = None,
        pub_date: datetime | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a NewsItem-like dictionary."""
        return {
            "url": url or f"https://example.com/news/{uuid.uuid4()}",
            "title": title or f"News Item {random.randint(1000, 9999)}",
            "description": description or "News item description",
            "source": source or "Test News Source",
            "source_host": source_host or "news.example.com",
            "pubDate": pub_date or datetime.now(timezone.utc),
            **kwargs,
        }

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[dict[str, Any]]:
        """Create multiple NewsItem objects."""
        return [NewsItemFactory.create(**kwargs) for _ in range(count)]


class SourceConfigFactory:
    """Factory for creating SourceConfig test objects."""

    @staticmethod
    def create(
        source_id: str | None = None,
        name: str | None = None,
        url: str | None = None,
        source_type: str = "rss",
        enabled: bool = True,
        interval_minutes: int = 30,
        per_host_concurrency: int = 2,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a SourceConfig-like dictionary."""
        return {
            "id": source_id or f"source_{random.randint(1000, 9999)}",
            "name": name or f"Test Source {random.randint(100, 999)}",
            "url": url or f"https://feeds.example.com/feed_{random.randint(1, 100)}.xml",
            "source_type": source_type,
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "per_host_concurrency": per_host_concurrency,
            **kwargs,
        }

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[dict[str, Any]]:
        """Create multiple SourceConfig objects."""
        return [SourceConfigFactory.create(**kwargs) for _ in range(count)]


class EntityFactory:
    """Factory for creating Entity test objects."""

    ENTITY_TYPES = ["PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "TECH"]

    @staticmethod
    def create(
        entity_id: str | None = None,
        canonical_name: str | None = None,
        entity_type: str | None = None,
        aliases: list[str] | None = None,
        description: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create an Entity-like dictionary."""
        name = canonical_name or f"Entity {random.randint(1000, 9999)}"
        return {
            "id": entity_id or str(uuid.uuid4()),
            "canonical_name": name,
            "type": entity_type or random.choice(EntityFactory.ENTITY_TYPES),
            "aliases": aliases or [name],
            "description": description or f"Description for {name}",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            **kwargs,
        }

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[dict[str, Any]]:
        """Create multiple Entity objects."""
        return [EntityFactory.create(**kwargs) for _ in range(count)]


class PipelineStateFactory:
    """Factory for creating PipelineState test objects."""

    @staticmethod
    def create(
        url: str | None = None,
        title: str | None = None,
        body: str | None = None,
        is_news: bool = True,
        category: str | None = None,
        language: str = "zh",
        score: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a PipelineState-like dictionary."""
        state = {
            "raw": {
                "url": url or f"https://example.com/article/{uuid.uuid4()}",
                "title": title or f"Pipeline Test Article {random.randint(1000, 9999)}",
                "body": body or "Pipeline test article body content.",
                "source": "Test Source",
                "source_host": "example.com",
                "publish_time": datetime.now(timezone.utc),
            },
            "is_news": is_news,
            "language": language,
        }

        if category:
            state["category"] = category
        if score is not None:
            state["score"] = score

        state.update(kwargs)
        return state

    @staticmethod
    def create_with_full_data(**kwargs) -> dict[str, Any]:
        """Create a complete PipelineState with all fields."""
        state = PipelineStateFactory.create(**kwargs)
        state.update({
            "cleaned": {
                "title": state["raw"]["title"],
                "body": state["raw"]["body"],
            },
            "category": kwargs.get("category", "tech"),
            "language": kwargs.get("language", "zh"),
            "region": kwargs.get("region", "CN"),
            "summary_info": {
                "summary": "Article summary text",
                "subjects": ["AI", "Technology"],
                "key_data": ["Key data point"],
                "impact": "high",
                "has_data": True,
            },
            "score": kwargs.get("score", 0.85),
            "sentiment": {
                "sentiment": "positive",
                "sentiment_score": 0.75,
                "primary_emotion": "joy",
            },
            "credibility": {
                "score": 0.9,
                "source_credibility": 0.85,
                "cross_verification": 0.8,
                "content_check": 0.95,
                "flags": [],
                "verified_by_sources": 2,
            },
            "entities": [
                {"text": "OpenAI", "label": "ORG"},
                {"text": "GPT-4", "label": "PRODUCT"},
            ],
            "vector": [random.random() for _ in range(1536)],
        })
        return state


class LLMResponseFactory:
    """Factory for creating LLM response test data."""

    @staticmethod
    def classify_response(is_news: bool = True, confidence: float = 0.95) -> str:
        """Create a classify LLM response."""
        import json
        return json.dumps({
            "is_news": is_news,
            "confidence": confidence,
        })

    @staticmethod
    def categorize_response(
        category: str = "tech",
        language: str = "zh",
        region: str = "CN",
    ) -> str:
        """Create a categorize LLM response."""
        import json
        return json.dumps({
            "category": category,
            "language": language,
            "region": region,
        })

    @staticmethod
    def analyze_response(
        summary: str = "Article summary",
        subjects: list[str] | None = None,
        sentiment: str = "neutral",
        sentiment_score: float = 0.5,
    ) -> str:
        """Create an analyze LLM response."""
        import json
        return json.dumps({
            "summary": summary,
            "subjects": subjects or ["Topic"],
            "key_data": [],
            "impact": "medium",
            "has_data": False,
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "primary_emotion": None,
        })

    @staticmethod
    def entity_response(entities: list[dict[str, str]] | None = None) -> str:
        """Create an entity extraction LLM response."""
        import json
        return json.dumps({
            "entities": entities or [
                {"text": "Entity1", "type": "PERSON"},
                {"text": "Entity2", "type": "ORG"},
            ],
        })


class VectorFactory:
    """Factory for creating vector test data."""

    @staticmethod
    def create_embedding(dimensions: int = 1536, seed: int | None = None) -> list[float]:
        """Create a random embedding vector."""
        if seed is not None:
            random.seed(seed)
        return [random.random() for _ in range(dimensions)]

    @staticmethod
    def create_similar_embedding(
        base: list[float],
        similarity: float = 0.9,
    ) -> list[float]:
        """Create an embedding similar to the base."""
        noise_level = 1 - similarity
        return [
            v + (random.random() - 0.5) * 2 * noise_level
            for v in base
        ]

    @staticmethod
    def create_batch(count: int, dimensions: int = 1536) -> list[list[float]]:
        """Create multiple embedding vectors."""
        return [VectorFactory.create_embedding(dimensions) for _ in range(count)]
