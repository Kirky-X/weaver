# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""URL Security module for Weaver application.

This module provides comprehensive URL security checking including:
- SSRF protection
- Malicious URL detection (URLhaus API, PhishTank)
- Heuristic analysis
- SSL certificate verification
- Data integrity signing
- Security audit utilities
"""

from core.security.api_key_manager import ApiKeyManager
from core.security.audit import (
    SecurityAuditReport,
    SecurityCheckResult,
    SecurityCheckSeverity,
    run_security_audit,
)
from core.security.audit_log_service import AuditLogService
from core.security.crypto.signing import (
    IntegrityError,
    SigningKey,
    load_signed_json,
    save_signed_json,
)
from core.security.models import CheckResult, CheckSource, URLRisk, ValidationResult
from core.security.traffic_detector import (
    TrafficAction,
    TrafficAnomalyConfig,
    TrafficAnomalyDetector,
    TrafficDecision,
)
from core.security.validation.ssrf import SSRFChecker, SSRFError
from core.security.validation.validator import URLValidator, URLValidatorConfig

__all__ = [
    "ApiKeyManager",
    "AuditLogService",
    "CheckResult",
    "CheckSource",
    "IntegrityError",
    "SSRFChecker",
    "SSRFError",
    "SecurityAuditReport",
    "SecurityCheckResult",
    "SecurityCheckSeverity",
    "SigningKey",
    "TrafficAction",
    "TrafficAnomalyConfig",
    "TrafficAnomalyDetector",
    "TrafficDecision",
    "URLRisk",
    "URLValidator",
    "URLValidatorConfig",
    "ValidationResult",
    "load_signed_json",
    "run_security_audit",
    "save_signed_json",
]
