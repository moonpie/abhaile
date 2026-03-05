"""Placeholder resolution for DNS record data."""

from __future__ import annotations

from typing import Any

from abhaile.utils.placeholders import resolve_placeholders


def _resolve_placeholder_value(value: Any, network: dict[str, Any]) -> Any:
    """Resolve placeholder values in strings.

    Delegates to the shared placeholder resolver.
    """
    return resolve_placeholders(value, network)
