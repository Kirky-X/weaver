"""Pipeline module - Data processing pipeline with LangGraph.

Note: Import Pipeline directly to avoid circular imports:
    from modules.pipeline.graph import Pipeline
"""

from modules.pipeline.state import PipelineState

__all__ = [
    "PipelineState",
]
