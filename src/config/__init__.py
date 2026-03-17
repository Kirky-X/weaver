"""Configuration module - Application settings and configuration.

This module provides:
- Settings: Pydantic settings model with environment variable support
- Configuration loading from TOML files

Example usage:
    from config.settings import Settings
    settings = Settings()
"""

from config.settings import Settings

__all__ = ["Settings"]
