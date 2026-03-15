"""Community detection module for knowledge graph clustering.

This module provides:
- Leiden algorithm for community detection
- Modularity calculation
- Community hierarchy management
- Community report generation
"""

from modules.community.leiden import LeidenClustering
from modules.community.models import Community, CommunityHierarchy
from modules.community.modularity import ModularityCalculator

__all__ = [
    "LeidenClustering",
    "Community",
    "CommunityHierarchy",
    "ModularityCalculator",
]
