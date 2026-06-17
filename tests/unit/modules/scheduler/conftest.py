# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for scheduler unit tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def scheduler_jobs_service():
    """Create SchedulerJobs instance with basic 7 dependencies (no pipeline)."""
    from modules.scheduler import SchedulerJobs

    return SchedulerJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
        graph_writer=MagicMock(),
        vector_repo=MagicMock(),
        article_repo=MagicMock(),
        source_authority_repo=MagicMock(),
        pending_sync_repo=MagicMock(),
    )


@pytest.fixture
def scheduler_jobs_service_with_pipeline():
    """Create SchedulerJobs instance with pipeline=MagicMock()."""
    from modules.scheduler import SchedulerJobs

    return SchedulerJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
        graph_writer=MagicMock(),
        vector_repo=MagicMock(),
        article_repo=MagicMock(),
        source_authority_repo=MagicMock(),
        pending_sync_repo=MagicMock(),
        pipeline=MagicMock(),
    )


@pytest.fixture
def scheduler_jobs_service_no_pipeline():
    """Create SchedulerJobs instance with pipeline=None."""
    from modules.scheduler import SchedulerJobs

    return SchedulerJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
        graph_writer=MagicMock(),
        vector_repo=MagicMock(),
        article_repo=MagicMock(),
        source_authority_repo=MagicMock(),
        pending_sync_repo=MagicMock(),
        pipeline=None,
    )
