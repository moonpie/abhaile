"""Jinja2 templating utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from abhaile.utils.network import strip_cidr


def create_jinja_env(
    template_dir: Path | str,
    additional_filters: dict[str, Callable] | None = None,
    trim_blocks: bool = True,
    lstrip_blocks: bool = True,
) -> Environment:
    """Create Jinja2 environment with standard Abhaile configuration.

    Args:
        template_dir: Directory containing templates.
        additional_filters: Optional dict of custom filters to register.
        trim_blocks: Whether to trim trailing newlines after blocks.
        lstrip_blocks: Whether to strip leading spaces before blocks.

    Returns:
        Configured Jinja2 Environment with standard filters.
    """
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=trim_blocks,
        lstrip_blocks=lstrip_blocks,
    )

    env.filters["strip_cidr"] = strip_cidr

    if additional_filters:
        env.filters.update(additional_filters)

    return env
