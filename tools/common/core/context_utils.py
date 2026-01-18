"""Context utilities for templates (shared).

Small helpers used by DNS and inventory tooling.
"""

import ipaddress


def strip_cidr(address: str | None) -> str | None:
    """Strip CIDR notation from an IP address.

    Accepts None/empty values and returns them unchanged for ergonomic use
    in templates and validators.
    """
    if address is None:
        return None
    if isinstance(address, str) and address.strip() == "":
        return ""
    return str(ipaddress.ip_interface(address).ip)


def last_octet(address: str) -> int:
    """Extract the last octet of an IP address.

    Args:
        address: IP address with optional CIDR (e.g., "172.20.20.10/24")

    Returns:
        Last octet as integer (e.g., 10)
    """
    ip = ipaddress.ip_interface(address).ip
    return int(str(ip).split(".")[-1])
