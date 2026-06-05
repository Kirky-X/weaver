"""Shared utilities for CLI scripts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config.settings import Settings
    from container import Container
    from modules.storage.postgres.article_repo import ArticleRepo


@dataclass
class ScriptContext:
    """Container for initialized script dependencies."""

    settings: Settings
    container: Container
    pipeline: Any
    article_repo: ArticleRepo


async def init_script_container(*, debug_logging: bool = False) -> ScriptContext:
    """Initialize container for CLI scripts.

    Encapsulates the common Settings -> Container -> init -> ArticleRepo sequence.

    Args:
        debug_logging: Enable debug-level logging.

    Returns:
        ScriptContext with all initialized dependencies.
    """
    import os

    from config.settings import Settings
    from container import Container, set_container, set_settings
    from core.observability.logging import configure_logging
    from modules.storage.postgres.article_repo import ArticleRepo

    settings = Settings()
    container = Container().configure(settings)
    set_container(container)
    set_settings(settings)

    if debug_logging or os.environ.get("DEBUG", "").lower() in ("true", "1", "yes"):
        configure_logging(debug=True)

    await container.init_strategy()
    await container.init_llm()
    pipeline = await container.init_pipeline()

    article_repo = ArticleRepo(container.relational_pool())

    return ScriptContext(
        settings=settings,
        container=container,
        pipeline=pipeline,
        article_repo=article_repo,
    )
