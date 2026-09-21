# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Sources API 调度接入测试。

验证运行时 create/update/delete 源时调度器的 interval job 生命周期：
- create_source 注册 interval job（否则运行时新建的源永不爬取）
- update_source 按 enabled 状态重调度/取消调度
- delete_source 移除 interval job（否则泄漏 job）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.endpoints.content.sources import (
    SourceCreateRequest,
    SourceUpdateRequest,
    create_source,
    delete_source,
    update_source,
)
from modules.ingestion.domain.models import SourceConfig


@pytest.fixture
def mock_scheduler() -> MagicMock:
    scheduler = MagicMock()
    scheduler.schedule_source = MagicMock()
    scheduler.unschedule_source = MagicMock()
    return scheduler


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.upsert = AsyncMock(side_effect=lambda config: config)
    repo.get = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=True)
    return repo


def _make_config(source_id: str = "test-source", enabled: bool = True) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name="Test Source",
        url="https://example.com/feed.xml",
        enabled=enabled,
    )


class TestCreateSourceScheduling:
    @pytest.mark.asyncio
    async def test_create_source_schedules_interval_job(
        self, mock_repo, mock_scheduler, monkeypatch
    ) -> None:
        """创建源后必须注册 interval job。"""
        monkeypatch.setattr("api.endpoints.content.sources._validate_source_url_ssrf", AsyncMock())
        monkeypatch.setattr("api.endpoints.content.sources._validate_feed_reachable", AsyncMock())

        request = SourceCreateRequest(
            id="new-source",
            name="New",
            url="https://example.com/feed.xml",
        )
        response = await create_source(
            request=request,
            _="key",
            repo=mock_repo,
            scheduler=mock_scheduler,
            fetcher=None,
        )

        assert response.data.id == "new-source"
        mock_scheduler.register_source.assert_called_once()
        mock_scheduler.schedule_source.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_source_skips_scheduling_helper_when_stopped(
        self, mock_repo, mock_scheduler, monkeypatch
    ) -> None:
        """调度器未启动时 schedule_source 是安全 no-op，不抛错。"""
        monkeypatch.setattr("api.endpoints.content.sources._validate_source_url_ssrf", AsyncMock())
        monkeypatch.setattr("api.endpoints.content.sources._validate_feed_reachable", AsyncMock())
        mock_scheduler.schedule_source = MagicMock(
            side_effect=lambda _src: None  # SourceScheduler 内部 no-op 语义
        )

        request = SourceCreateRequest(
            id="new-source",
            name="New",
            url="https://example.com/feed.xml",
        )
        response = await create_source(
            request=request,
            _="key",
            repo=mock_repo,
            scheduler=mock_scheduler,
            fetcher=None,
        )
        assert response.data.id == "new-source"


class TestUpdateSourceRescheduling:
    @pytest.mark.asyncio
    async def test_update_enabled_source_reschedules(self, mock_repo, mock_scheduler) -> None:
        """enabled 源更新 interval 后必须重调度。"""
        existing = _make_config()
        mock_repo.get = AsyncMock(return_value=existing)

        request = SourceUpdateRequest(interval_minutes=60)
        response = await update_source(
            source_id="test-source",
            request=request,
            _="key",
            repo=mock_repo,
            scheduler=mock_scheduler,
        )

        assert response.data.interval_minutes == 60
        mock_scheduler.schedule_source.assert_called_once_with(existing)
        mock_scheduler.unschedule_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_disable_source_unschedules(self, mock_repo, mock_scheduler) -> None:
        """禁用源必须移除 interval job。"""
        existing = _make_config(enabled=True)
        mock_repo.get = AsyncMock(return_value=existing)

        request = SourceUpdateRequest(enabled=False)
        await update_source(
            source_id="test-source",
            request=request,
            _="key",
            repo=mock_repo,
            scheduler=mock_scheduler,
        )

        assert existing.enabled is False
        mock_scheduler.unschedule_source.assert_called_once_with("test-source")
        mock_scheduler.schedule_source.assert_not_called()


class TestDeleteSourceUnscheduling:
    @pytest.mark.asyncio
    async def test_delete_source_removes_interval_job(self, mock_repo, mock_scheduler) -> None:
        """删除源必须移除 interval job，否则 job 泄漏。"""
        await delete_source(
            source_id="test-source",
            _="key",
            repo=mock_repo,
            scheduler=mock_scheduler,
        )

        mock_repo.delete.assert_called_once_with("test-source")
        mock_scheduler.unschedule_source.assert_called_once_with("test-source")

    @pytest.mark.asyncio
    async def test_delete_missing_source_does_not_unschedule(self, mock_scheduler) -> None:
        """源不存在（404）时不应触碰调度器。"""
        mock_repo = MagicMock()
        mock_repo.delete = AsyncMock(return_value=False)

        from core.exceptions import BusinessError

        with pytest.raises(BusinessError):
            await delete_source(
                source_id="missing",
                _="key",
                repo=mock_repo,
                scheduler=mock_scheduler,
            )
        mock_scheduler.unschedule_source.assert_not_called()
