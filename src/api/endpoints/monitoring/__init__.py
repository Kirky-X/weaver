"""Monitoring API endpoints - read-only observation endpoints.

This module contains all monitoring and observation endpoints:
- llm: LLM failure and usage monitoring
- memory: Memory system diagnostics
- causal: Causal graph statistics
- graph: Graph quality metrics
- communities: Community health monitoring
- alerts: Alert rule CRUD, trigger, and acknowledgment
"""

from api.endpoints.monitoring.alerts import router as alerts_router
from api.endpoints.monitoring.causal import router as causal_router
from api.endpoints.monitoring.communities import router as communities_monitoring_router
from api.endpoints.monitoring.graph import router as graph_monitoring_router
from api.endpoints.monitoring.llm import router as llm_router
from api.endpoints.monitoring.memory import router as memory_router

__all__ = [
    "alerts_router",
    "causal_router",
    "communities_monitoring_router",
    "graph_monitoring_router",
    "llm_router",
    "memory_router",
]
