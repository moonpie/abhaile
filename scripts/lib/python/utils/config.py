"""Configuration file loading (YAML and JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from utils.errors import RenderError


def read_yaml(path: Path) -> Any:
    """Load YAML file.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML data.

    Raises:
        RenderError: If file cannot be read or parsed.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:
        raise RenderError(f"Failed to read YAML: {path} ({exc})") from exc


def read_json(path: Path) -> Any:
    """Load JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed JSON data.

    Raises:
        RenderError: If file cannot be read or parsed.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise RenderError(f"Failed to read JSON: {path} ({exc})") from exc
