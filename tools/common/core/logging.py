"""Standardized logging configuration for Abhaile tools.

Provides consistent logging setup across CLI tools and library modules.
"""

import logging
import sys
from typing import Literal

__all__ = ["setup_logging", "get_logger"]

# Default format for all loggers
DEFAULT_FORMAT = "%(levelname)s: %(message)s"
VERBOSE_FORMAT = "[%(name)s] %(levelname)s: %(message)s"


def setup_logging(
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | int = logging.INFO,
    verbose: bool = False,
    format: str | None = None,
) -> None:
    """Configure logging for CLI tools.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR) or int
        verbose: If True, use verbose format with module names
        format: Custom format string (overrides verbose setting)

    Usage:
        # Simple setup
        setup_logging()

        # Debug mode
        setup_logging(level="DEBUG")

        # Verbose mode with module names
        setup_logging(verbose=True)

        # Custom format
        setup_logging(format="%(asctime)s - %(message)s")
    """
    # Convert string level to int if needed
    if isinstance(level, str):
        level = getattr(logging, level.upper())

    # Choose format
    if format is None:
        format = VERBOSE_FORMAT if verbose else DEFAULT_FORMAT

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=format,
        stream=sys.stderr,
        force=True,  # Reconfigure if already configured
    )


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance

    Usage:
        logger = get_logger(__name__)
        logger.info("Starting process")
    """
    return logging.getLogger(name)
