"""Validate DNS configuration in network.yaml."""

from __future__ import annotations

from typing import Any

from utils.errors import RenderError


def validate_dns_serials(network: dict[str, Any]) -> None:
    """Validate DNS zone serials for content hash mismatches.

    This is a pre-render validation that checks if zone content has changed
    since the last serial update. Collects all mismatches and reports them together.

    Args:
        network: Network configuration from network.yaml.

    Raises:
        RenderError: If any zones have content changed but serial not updated.
    """
    if "dns" not in network or "zones" not in network["dns"]:
        return

    zones = network["dns"]["zones"]

    # Import here to avoid circular dependency
    from renderers.dns import _validate_zone_serial_collect

    errors = _validate_zone_serial_collect(zones, network)

    if errors:
        error_message = (
            "DNS zone serials out of sync:\n\n"
            + "\n\n".join(errors)
            + "\n\nUpdate all zones in config/network.yaml and re-run render."
        )
        raise RenderError(error_message)
