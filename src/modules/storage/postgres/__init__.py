# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""PostgreSQL storage submodule."""

from modules.storage.postgres.article_repo import ArticleRepo
from modules.storage.postgres.article_version_repo import ArticleVersionRepo
from modules.storage.postgres.outbox_repo import OutboxRepo
from modules.storage.postgres.pending_sync_repo import PendingSyncRepo
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo
from modules.storage.postgres.vector_repo import VectorRepo

__all__ = [
    "ArticleRepo",
    "ArticleVersionRepo",
    "OutboxRepo",
    "PendingSyncRepo",
    "SourceAuthorityRepo",
    "VectorRepo",
]
