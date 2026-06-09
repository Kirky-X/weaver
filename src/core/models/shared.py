from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArticleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_url: str
    source_host: str | None = None
    is_news: bool = False
    title: str
    body: str | None = None
    category: str | None = None
    language: str | None = None
    region: str | None = None
    summary: str | None = None
    subjects: list[str] | None = None
    key_data: list[str] | None = None
    impact: str | None = None
    has_data: bool | None = None
    score: float | None = None
    quality_score: float | None = None
    data_conflicts: list[dict[str, Any]] = []
    image_forensics: list[dict[str, Any]] = []
    document_type: str = "news"
    doc_metadata: dict[str, Any] = {}
    content_hash: str | None = None
    version: int = 1
    sentiment: str | None = None
    sentiment_score: float | None = None
    primary_emotion: str | None = None
    emotion_targets: list[str] | None = None
    credibility_score: float | None = None
    source_credibility: float | None = None
    cross_verification: float | None = None
    content_check_score: float | None = None
    credibility_flags: list[str] | None = None
    persist_status: str = "pending"
    publish_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EntityView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    neo4j_id: str
    canonical_name: str = Field(validation_alias="name")
    entity_type: str
    aliases: list[str] = []
    description: str | None = None
    tier: int = 2
    article_count: int = 0


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    event_type: str
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    article_count: int = 0


class CommunityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    member_count: int = 0
    keywords: list[str] = []
