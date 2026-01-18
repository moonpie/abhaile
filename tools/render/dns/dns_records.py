"""DNS record helpers."""

from __future__ import annotations

from typing import Any, Iterable

from tools.common.core import resolve_placeholders


def format_a_records(records: Iterable[str]) -> list[dict[str, Any]]:
    """Return list of dicts for A records from iterable of IPs."""
    return [{"type": "A", "value": ip} for ip in records]


def resolve_placeholder(placeholder: str, network: dict[str, Any]) -> str:
    """Resolve a single placeholder string against the network context."""

    if not (placeholder.startswith("%%") and placeholder.endswith("%%")):
        return placeholder

    return resolve_placeholders(placeholder, network)
