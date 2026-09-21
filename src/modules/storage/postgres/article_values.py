# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Shared ArticleCore/ArticleBody value construction from RawArticle.

Single implementation of the body-length description fallback, URL
normalization, and content-hash computation used by ``insert_raw`` and
``bulk_insert_raw``. Previously copy-pasted across article_reader,
article_writer, and raw_bulk_writer.
"""

from __future__ import annotations

from typing import Any

from core.change_detector import ChangeDetector
from core.db import CategoryType, PersistStatus
from core.observability import get_logger
from core.url_utils import normalize_url

log = get_logger(__name__)

# Minimum body length to consider a fetch successful (vs anti-bot error page)
MIN_BODY_LENGTH = 200


def resolve_effective_body(body: str, description: str | None) -> tuple[str, str]:
    """Return (effective_body, body_source), falling back to description
    when the fetched body is shorter than MIN_BODY_LENGTH.

    Both the row-construction path and the content-hash dedup path must use
    this so the stored hash always matches the stored body.
    """
    if len(body) < MIN_BODY_LENGTH and description:
        return description, "description"
    return body, "full"


def build_core_body_values(raw: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build ArticleCore / ArticleBody kwargs + body_source for a RawArticle.

    Shared by ``insert_raw`` and ``bulk_insert_raw`` to keep body-length
    fallback, normalization, and content-hash logic in one place.

    Args:
        raw: RawArticle with non-empty url.

    Returns:
        Tuple of (core_kwargs, body_kwargs, body_source) where body_source
        is "full" or "description" (the latter when raw.body < MIN_BODY_LENGTH
        and a description fallback is available).
    """
    effective_body, body_source = resolve_effective_body(raw.body, raw.description)
    if body_source == "description":
        log.info(
            "body_too_short_using_description",
            url=raw.url,
            body_len=len(raw.body),
            desc_len=len(raw.description),
        )

    normalized_url = normalize_url(raw.url)
    content_hash = ChangeDetector.compute_hash({"title": raw.title or "", "body": effective_body})

    core_kwargs: dict[str, Any] = {
        "source_url": normalized_url,
        "source_host": raw.source_host or "",
        "source_id": raw.source_id,
        "title": raw.title or "",
        # 入库即写回退值（与 persistence._persist_articles_to_pg 的
        # setdefault 一致）：ingestion 层不产分类/语言/地区，若不在此
        # 兜底，worker 中断后这些列将停留 NULL。categorizer/analyze
        # 完成后由 upsert 的 ON CONFLICT 用真实值覆盖（category 另有
        # NULL 守卫，不会回退成空）。
        "category": CategoryType.OTHER,
        "language": "unknown",
        "region": "unknown",
        "persist_status": PersistStatus.PENDING,
        "content_hash": content_hash,
    }
    if raw.publish_time:
        core_kwargs["publish_time"] = raw.publish_time

    body_kwargs: dict[str, Any] = {"body": effective_body}
    return core_kwargs, body_kwargs, body_source
