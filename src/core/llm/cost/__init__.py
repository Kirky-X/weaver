# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM cost calculation (D2 / audit-unintegrated-modules).

Moved from modules.analytics.llm_usage to core.llm.cost to keep
core.llm.client free of runtime dependencies on the modules layer.
"""

from core.llm.cost.calculator import CostCalculator

__all__ = ["CostCalculator"]
