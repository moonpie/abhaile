"""Inventory analyzers - derive insights from collected data.

Analyzers take raw collected data and produce structured analysis.
"""

from __future__ import annotations

from typing import Any

from tools.common.core import get_logger

logger = get_logger(__name__)


def analyze_dns_zones(zones: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze DNS zones by provider.

    Args:
        zones: List of zone dicts from network.yaml dns.zones

    Returns:
        Dict with 'internal' and 'external' zone lists and counts
    """
    internal = []
    external = []

    for zone in zones:
        name = zone.get("name", "").rstrip(".")
        provider = zone.get("provider", "")

        if provider in ["coredns-common", "coredns-filtered", "coredns-clean"]:
            internal.append(name)
        elif provider in ["desec.io", "desec"]:
            external.append(name)
        else:
            # Default to internal if unknown provider
            internal.append(name)

    logger.info(
        f"Analyzed {len(internal)} internal and {len(external)} external DNS zones"
    )

    return {
        "internal": sorted(internal),
        "external": sorted(external),
        "total_internal": len(internal),
        "total_external": len(external),
    }
