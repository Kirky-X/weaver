# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Evidence sampling module for long document processing.

This module provides Monte Carlo-based evidence sampling for efficiently
processing long documents by extracting the most relevant regions.
"""

from core.evidence.mc_sampler import MCSampler
from core.evidence.models import EvidenceScoreOutput, ROISummaryOutput

__all__ = [
    "MCSampler",
    "EvidenceScoreOutput",
    "ROISummaryOutput",
]
