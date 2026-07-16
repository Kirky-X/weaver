# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Evidence sampling module for long document processing.

This module provides Monte Carlo-based evidence sampling for efficiently
processing long documents by extracting the most relevant regions.
"""

from core.evidence.mc_sampler import MCSampler
from core.evidence.models import EvidenceScoreOutput, ROISummaryOutput

__all__ = [
    "EvidenceScoreOutput",
    "MCSampler",
    "ROISummaryOutput",
]
