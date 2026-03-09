"""DNS utility helpers."""

from __future__ import annotations

from abhaile.utils.errors import RenderError


def _ip_to_reverse_dns(ip_address: str) -> str:
    """Convert IPv4 address to reverse DNS notation.

    Args:
        ip_address: IPv4 address (e.g., '192.168.1.10').

    Returns:
        Reverse DNS notation (e.g., '10.1.168.192.in-addr.arpa.').
    """
    parts = ip_address.split(".")
    if len(parts) != 4:
        raise RenderError(f"Invalid IPv4 address: {ip_address}")
    return ".".join(reversed(parts)) + ".in-addr.arpa."
