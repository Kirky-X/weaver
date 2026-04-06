# Copyright (c) 2026 KirkyX. All Rights Reserved
"""URL Security module for Weaver application.

This module provides comprehensive URL security checking including:
- SSRF protection
- Malicious URL detection (URLhaus API, PhishTank)
- Heuristic analysis
- SSL certificate verification
"""

from core.security.models import CheckResult, CheckSource, URLRisk, ValidationResult
from core.security.ssrf import SSRFChecker, SSRFError
from core.security.validator import URLValidator, URLValidatorConfig

# Backward compatibility alias
URLValidationError = SSRFError

__all__ = [
    "CheckResult",
    "CheckSource",
    "SSRFChecker",
    "SSRFError",
    "URLRisk",
    "URLValidationError",
    "URLValidator",
    "URLValidatorConfig",
    "ValidationResult",
]
