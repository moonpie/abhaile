"""Shared placeholder resolution utilities."""

from __future__ import annotations

import re
from typing import Any, Callable

from abhaile.utils.errors import RenderError
from abhaile.utils.network import strip_cidr

_PLACEHOLDER_PATTERN = re.compile(r"%%(.*?)%%")

# Filter registry: maps filter names to their implementations.
# Filters are functions that take a string and return a string.
# To add a new filter, add an entry here.
# Don't forget to add tests for new filters
_PLACEHOLDER_FILTERS: dict[str, Callable[[str], str]] = {
    "strip_cidr": strip_cidr,
}


def get_available_placeholder_filters() -> list[str]:
    """Return a sorted list of available placeholder filters.

    Useful for documentation and error messages.

    Returns:
        Sorted list of filter names.
    """
    return sorted(_PLACEHOLDER_FILTERS.keys())


def resolve_placeholder_value(value: Any, network: dict[str, Any]) -> Any:
    """Resolve placeholder values in strings.

    Handles expressions like '%%network.services.vault.address | strip_cidr%%'.

    Args:
        value: Value to resolve (string with placeholders or other type).
        network: Network configuration dict.

    Returns:
        Resolved value.
    """
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match[str]) -> str:
        """Resolve a single placeholder match with optional filters."""
        expression = match.group(1).strip()
        placeholder_text = f"%%{match.group(1)}%%"
        parts = [part.strip() for part in expression.split("|") if part.strip()]
        if not parts:
            raise RenderError(f"Empty placeholder expression: {placeholder_text}")

        try:
            current = _lookup_network_value(parts[0], network)
        except RenderError as e:
            raise RenderError(f"{str(e)} in placeholder: {placeholder_text}") from e

        for part in parts[1:]:
            if part not in _PLACEHOLDER_FILTERS:
                available = ", ".join(get_available_placeholder_filters())
                raise RenderError(
                    f"Unknown placeholder filter: {part} in placeholder: {placeholder_text}. "
                    f"Available filters: {available}"
                )
            filter_func = _PLACEHOLDER_FILTERS[part]
            current = filter_func(str(current))
        return str(current)

    return _PLACEHOLDER_PATTERN.sub(_replace, value)


def resolve_placeholders(value: Any, network: dict[str, Any]) -> Any:
    """Resolve placeholders in strings, dicts, and lists.

    Args:
        value: Value to resolve (string, dict, list, or other type).
        network: Network configuration dict.

    Returns:
        Value with placeholders resolved.
    """
    if isinstance(value, dict):
        return {key: resolve_placeholders(item, network) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_placeholders(item, network) for item in value]
    return resolve_placeholder_value(value, network)


def _lookup_network_value(path_expr: str, network: dict[str, Any]) -> Any:
    """Look up a value in the network dict using dot notation.

    Handles keys that contain dots (e.g., interface names like 'enp0s31f6.100')
    by trying progressively longer key combinations.

    Args:
        path_expr: Dot-separated path starting with 'network.' (e.g., 'network.services.vault.address').
        network: Network configuration dict.

    Returns:
        Value at the specified path.

    Raises:
        RenderError: If path not found or doesn't start with 'network.'.
    """
    if not path_expr.startswith("network."):
        raise RenderError(f"Unsupported placeholder root: {path_expr}")

    parts = path_expr.split(".")[1:]
    current: Any = network

    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            raise RenderError(f"Placeholder path not found: {path_expr}")

        found = False
        for length in range(len(parts) - i, 0, -1):
            candidate_key = ".".join(parts[i : i + length])
            if candidate_key in current:
                current = current[candidate_key]
                i += length
                found = True
                break

        if not found:
            raise RenderError(f"Placeholder path not found: {path_expr}")

    return current
