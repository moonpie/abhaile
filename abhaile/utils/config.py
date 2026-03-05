"""Configuration file loading (YAML and JSON)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from abhaile.utils.errors import RenderError


def _path_cache_key(path: Path) -> tuple[str, int, int]:
    """Return a stable cache key for a config file path.

    Key is based on resolved path + mtime + size, so cache entries are naturally
    invalidated when content changes.
    """
    resolved = path.resolve(strict=False)
    stat = resolved.stat()
    return str(resolved), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=256)
def _read_yaml_cached(path_str: str, _: int, __: int) -> Any:
    """Read and parse YAML from a cacheable key."""
    with Path(path_str).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@lru_cache(maxsize=256)
def _read_json_cached(path_str: str, _: int, __: int) -> Any:
    """Read and parse JSON from a cacheable key."""
    with Path(path_str).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clear_config_cache() -> None:
    """Clear YAML/JSON read caches.

    Intended for use at the start of a render invocation to keep cache lifetime
    scoped to one CLI run.
    """
    _read_yaml_cached.cache_clear()
    _read_json_cached.cache_clear()


def read_yaml(path: Path) -> Any:
    """Load YAML file.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML data.

    Raises:
        RenderError: If file cannot be read or parsed (YAML syntax error,
            file not found, permission denied, or other OS error).
    """
    try:
        return _read_yaml_cached(*_path_cache_key(path))
    except (yaml.YAMLError, FileNotFoundError, PermissionError, OSError) as exc:
        raise RenderError(f"Failed to read YAML: {path} ({exc})") from exc


def ensure_mapping(data: Any, path: Path) -> dict[str, Any]:
    """Ensure loaded config data is a YAML mapping.

    Args:
        data: Parsed YAML data.
        path: Source file path for error context.

    Returns:
        Mapping data.

    Raises:
        RenderError: If parsed data is not a mapping.
    """
    if not isinstance(data, dict):
        raise RenderError(f"Expected YAML mapping in {path}")
    return data


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load YAML and require a top-level mapping.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML mapping.

    Raises:
        RenderError: If file cannot be read/parsed or top-level value is not a mapping.
    """
    return ensure_mapping(read_yaml(path), path)


def read_json(path: Path) -> Any:
    """Load JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed JSON data.

    Raises:
        RenderError: If file cannot be read or parsed (JSON syntax error,
            file not found, permission denied, or other OS error).
    """
    try:
        return _read_json_cached(*_path_cache_key(path))
    except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError) as exc:
        raise RenderError(f"Failed to read JSON: {path} ({exc})") from exc
