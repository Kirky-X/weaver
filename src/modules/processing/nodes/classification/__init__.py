# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Classification processing nodes."""

from modules.processing.nodes.classification.cascade_classifier import CascadeClassifier
from modules.processing.nodes.classification.categorizer import (
    CascadeCategorizerNode,
    normalize_category,
    normalize_emotion,
)
from modules.processing.nodes.classification.classifier import CascadeClassifierNode
from modules.processing.nodes.classification.credibility_checker import (
    RuleBasedCredibilityCheckerNode,
)

__all__ = [
    "CascadeCategorizerNode",
    "CascadeClassifier",
    "CascadeClassifierNode",
    "RuleBasedCredibilityCheckerNode",
    "normalize_category",
    "normalize_emotion",
]
