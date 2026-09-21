# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

"""分析统计域 - LLM 失败记录。

当前公开 API 为 ``LLMFailureRepo``（实现于本包 ``repo.py``）。
``modules.scheduler`` 中的 ``llm_failure_cleanup`` 调度任务仍持有独立的
repo 引用，其迁移（Phase 5 收尾）尚未完成。
"""

from modules.analytics.llm_failure.repo import LLMFailureRepo

__all__ = ["LLMFailureRepo"]
