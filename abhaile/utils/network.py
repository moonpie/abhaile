"""Network utility functions."""


def strip_cidr(address: str) -> str:
    """Strip CIDR suffix from IP address.

    Args:
        address: IP address with optional CIDR (e.g., '192.168.1.1/24').

    Returns:
        IP address without CIDR suffix.

    Examples:
        >>> strip_cidr("192.168.1.1/24")
        "192.168.1.1"
        >>> strip_cidr("192.168.1.1")
        "192.168.1.1"
    """
    return address.split("/")[0] if "/" in address else address
