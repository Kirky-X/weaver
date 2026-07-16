# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Malicious URL detection modules.

This package contains various URL security checkers:
- URLhausClient: Real-time malicious URL lookup via URLhaus API
- PhishTankSync: Offline phishing URL blacklist
- HeuristicChecker: Heuristic analysis for suspicious URL patterns
- SSLVerifier: SSL certificate verification
"""

from .heuristic_checker import HeuristicChecker
from .phishtank_sync import PhishTankSync
from .ssl_verifier import SSLVerifier
from .urlhaus_client import URLhausClient, URLhausResponse, URLhausStatus

__all__ = [
    "HeuristicChecker",
    "PhishTankSync",
    "SSLVerifier",
    "URLhausClient",
    "URLhausResponse",
    "URLhausStatus",
]
