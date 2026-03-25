# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Health check module for service availability validation.

This module provides pre-startup health checking functionality to ensure
all required services are available before the application starts.
"""

from core.health.env_validator import (
    EnvironmentValidator,
    ValidationResult,
    validate_environment,
)
from core.health.pre_startup import (
    PreStartupHealthChecker,
    ServiceCheckResult,
    run_pre_startup_health_check,
)

__all__ = [
    "EnvironmentValidator",
    "PreStartupHealthChecker",
    "ServiceCheckResult",
    "ValidationResult",
    "run_pre_startup_health_check",
    "validate_environment",
]
