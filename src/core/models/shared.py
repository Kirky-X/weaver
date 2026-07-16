# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArticleView(BaseModel):
    """Article view model aligned with ADD §1.5.1.

    Implements: Data Contract Layer — ArticleView
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_url: str
    source_host: str | None = None
    title: str
    body: str | None = None
    category: str | None = None
    language: str | None = None
    region: str | None = None
    summary: str | None = None
    subjects: list[str] | None = None
    key_data: list[str] | None = None
    score: float | None = None
    quality_score: float | None = None
    data_conflicts: list[dict[str, Any]] = []
    sentiment: str | None = None
    sentiment_score: float | None = None
    emotion_targets: list[str] | None = None
    credibility_score: float | None = None
    cross_verification: float | None = None
    persist_status: str = "pending"
    verified_by_sources: int = 0
    publish_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EntityView(BaseModel):
    """Entity view model aligned with ADD §1.5.1.

    Implements: Data Contract Layer — EntityView
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(validation_alias="neo4j_id")
    canonical_name: str = Field(validation_alias="name")
    type: str = Field(validation_alias="entity_type")
    aliases: list[str] = []
    description: str | None = None
    degree: int = 0
    community_id: str | None = None
    confidence: float = 1.0
    last_mentioned: datetime | None = None


class EventView(BaseModel):
    """Event view model aligned with ADD §1.5.1.

    Implements: Data Contract Layer — EventView
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    summary: str = Field(validation_alias="name")
    type: str = Field(validation_alias="event_type")
    description: str | None = None
    time: datetime | None = Field(default=None, validation_alias="start_time")
    location: str | None = None
    status: str = "confirmed"
    importance: float = 0.5
    participants: list[dict[str, Any]] = (
        []
    )  # [{"entity_id": "ent_1", "role": "initiator", "confidence": 0.95}]
    narratives: list[dict[str, Any]] = (
        []
    )  # [{"text": "description", "source": "article_id", "confidence": 0.8}]
    source_article_id: str | None = None


class CommunityView(BaseModel):
    """Community view model aligned with ADD §1.5.1.

    Implements: Data Contract Layer — CommunityView
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    title: str = Field(validation_alias="name")
    summary: str | None = Field(default=None, validation_alias="description")
    keywords: list[str] = []
    level: int = 0
    rank: float = 0.0
    entity_count: int = 0
    article_count: int = 0
    embedding: list[float] | None = None


class ArticleSearchResultView(BaseModel):
    """Search result view for article vector similarity search.

    Implements: Data Contract Layer — ArticleSearchResultView
    """

    model_config = ConfigDict(from_attributes=True)

    article_id: str
    category: str | None = None
    similarity: float
    hybrid_score: float | None = None
    publish_time: datetime | None = None
    created_at: datetime | None = None


class EntitySearchResultView(BaseModel):
    """Search result view for entity vector similarity search.

    Implements: Data Contract Layer — EntitySearchResultView
    """

    model_config = ConfigDict(from_attributes=True)

    neo4j_id: str
    similarity: float


class CommunitySearchResultView(BaseModel):
    """Search result view for community vector similarity search.

    Implements: Data Contract Layer — CommunitySearchResultView
    """

    model_config = ConfigDict(from_attributes=True)

    community_id: str
    score: float
    title: str | None = None
    summary: str | None = None
