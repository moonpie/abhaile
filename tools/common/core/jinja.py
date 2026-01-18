"""Shared Jinja2 environment factory."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Mapping

from jinja2 import Environment, FileSystemLoader, StrictUndefined

__all__ = ["get_jinja_env"]


def get_jinja_env(
    search_paths: Iterable[str | Path], *, filters: Mapping[str, Callable] | None = None
) -> Environment:
    """Construct a Jinja2 environment with standard settings.

    Args:
        search_paths: Paths to search for templates.
        filters: Optional mapping of filter names to callables to register.

    Returns:
        Configured Jinja2 Environment instance.
    """
    loader_paths = [str(path) for path in search_paths]
    env = Environment(
        loader=FileSystemLoader(loader_paths),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    if filters:
        env.filters.update(filters)
    return env
