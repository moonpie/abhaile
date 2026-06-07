"""Configuration file loading (YAML and JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from abhaile.utils.errors import RenderError

_YAML_CACHE: dict[str, Any] = {}


def clear_config_cache() -> None:
    """Clear cached config state between render passes."""
    _YAML_CACHE.clear()


def read_yaml(path: Path) -> Any:
    """Load YAML file, returning cached result if available."""
    key = str(path.resolve())
    if key in _YAML_CACHE:
        return _YAML_CACHE[key]
    try:
        with path.open("r", encoding="utf-8") as handle:
            result = yaml.safe_load(handle)
    except (yaml.YAMLError, FileNotFoundError, PermissionError, OSError) as exc:
        raise RenderError(f"Failed to read YAML: {path} ({exc})") from exc
    _YAML_CACHE[key] = result
    return result


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
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError) as exc:
        raise RenderError(f"Failed to read JSON: {path} ({exc})") from exc
