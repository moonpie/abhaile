"""Shared CLI utilities for abhaile commands."""

from __future__ import annotations

import logging


def configure_logging(verbosity: int) -> None:
    """Configure CLI logging verbosity."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s event=%(message)s",
    )
