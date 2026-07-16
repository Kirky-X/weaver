# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Scheduler module - Background job scheduling.

Core scheduling functionality:
- SchedulerJobs: Job scheduler facade (composition root)
- ConsistencyJobs: Retry, sync, and consistency jobs
- MaintenanceJobs: Cleanup and archival jobs
- AnalyticsJobs: Aggregation, briefing, and signal detection jobs

公开 API:
- SchedulerJobs: 任务调度器（向后兼容外观）
- ConsistencyJobs: 一致性任务
- MaintenanceJobs: 维护任务
- AnalyticsJobs: 分析任务
- scheduled_task: 任务装饰器
"""

from modules.scheduler.analytics_jobs import AnalyticsJobs
from modules.scheduler.consistency_jobs import ConsistencyJobs
from modules.scheduler.jobs import SchedulerJobs
from modules.scheduler.maintenance_jobs import MaintenanceJobs
from modules.scheduler.wrapper import scheduled_task

__all__ = [
    "AnalyticsJobs",
    "ConsistencyJobs",
    "MaintenanceJobs",
    "SchedulerJobs",
    "scheduled_task",
]
