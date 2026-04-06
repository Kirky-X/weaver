# Copyright (c) 2026 KirkyX. All Rights Reserved
"""URL Security module for Weaver application.

This module provides comprehensive URL security checking including:
- SSRF protection
- Malicious URL detection (URLhaus API, PhishTank)
- Heuristic analysis
- SSL certificate verification
- Data integrity signing
- Security audit utilities
"""

from core.security.audit import (
    SecurityAuditReport,
    SecurityCheckResult,
    SecurityCheckSeverity,
    run_security_audit,
)
from core.security.models import CheckResult, CheckSource, URLRisk, ValidationResult
from core.security.signing import (
    IntegrityError,
    SigningKey,
    SigningKeyError,
    load_signed_json,
    save_signed_json,
)
from core.security.ssrf import SSRFChecker, SSRFError
from core.security.validator import URLValidator, URLValidatorConfig

# Backward compatibility alias
URLValidationError = SSRFError

__all__ = [
    "CheckResult",
    "CheckSource",
    "IntegrityError",
    "SSRFChecker",
    "SSRFError",
    "SecurityAuditReport",
    "SecurityCheckResult",
    "SecurityCheckSeverity",
    "SigningKey",
    "SigningKeyError",
    "URLRisk",
    "URLValidationError",
    "URLValidator",
    "URLValidatorConfig",
    "ValidationResult",
    "load_signed_json",
    "run_security_audit",
    "save_signed_json",
]
