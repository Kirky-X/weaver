# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""SQLAlchemy 2.0 ORM models for the weaver system.

This package splits the original monolithic ``models.py`` into focused
submodules while re-exporting every class here for backward compatibility.
Existing imports such as ``from core.db.models import Article`` continue
to work without changes.
"""

from core.db.models.alert import AlertEvent, AlertRule
from core.db.models.article import (
    Article,
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    ArticleProcessing,
    ArticleVector,
    ArticleVersion,
)
from core.db.models.base import (
    Base,
    CategoryType,
    EmotionType,
    JSONCompatible,
    PersistStatus,
    VectorType,
)
from core.db.models.llm import (
    LLMCompareHourly,
    LLMFailureRecord,
    LLMUsageHourly,
    LLMUsageRaw,
)
from core.db.models.misc import (
    ApiKey,
    AuditLog,
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    EntityVector,
    PromptTemplate,
    RelationType,
    RelationTypeAlias,
    SentimentShift,
    SourceAuthority,
    SourceConfig,
    UnknownRelationType,
)
from core.db.models.saga import PendingSync, SagaLog

__all__ = [
    "AlertEvent",
    "AlertRule",
    "ApiKey",
    "Article",
    "ArticleAnalysis",
    "ArticleBody",
    "ArticleCore",
    "ArticleProcessing",
    "ArticleVector",
    "ArticleVersion",
    "AuditLog",
    "Base",
    "CategoryType",
    "CommunityVector",
    "DailyBriefing",
    "DailyBriefingItem",
    "EmotionType",
    "EntityVector",
    "JSONCompatible",
    "LLMCompareHourly",
    "LLMFailureRecord",
    "LLMUsageHourly",
    "LLMUsageRaw",
    "PendingSync",
    "PersistStatus",
    "PromptTemplate",
    "RelationType",
    "RelationTypeAlias",
    "SagaLog",
    "SentimentShift",
    "SourceAuthority",
    "SourceConfig",
    "UnknownRelationType",
    "VectorType",
]
