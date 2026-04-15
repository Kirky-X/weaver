# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Configuration module - Application settings and configuration.

This module provides:
- Settings: Pydantic settings model with environment variable support
- Configuration loading from TOML files

Example usage:
    from src.config.settings import Settings
    settings = Settings()
"""

from src.config.settings import Settings

__all__ = ["Settings"]
