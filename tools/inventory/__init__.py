"""Abhaile inventory generation system.

Generates structured inventory markdown files from rendered output
and configuration.
"""

from tools.common.core import setup_logging, get_logger


# ============================================================================
# Error Classes
# ============================================================================


class InventoryError(Exception):
    """Base inventory generation error."""

    pass


class ConfigError(InventoryError):
    """Configuration file error (missing, invalid format)."""

    pass


class MissingConfigError(ConfigError):
    """Required configuration file not found."""

    pass


class MissingServiceError(InventoryError):
    """Service.yaml file missing for deployed service."""

    pass


class RenderError(InventoryError):
    """Rendered output incomplete or invalid."""

    pass


class MissingRenderedError(RenderError):
    """Rendered output directory or files not found."""

    pass


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "setup_logging",
    "get_logger",
    "InventoryError",
    "ConfigError",
    "MissingConfigError",
    "MissingServiceError",
    "RenderError",
    "MissingRenderedError",
]
