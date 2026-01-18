"""deSEC DNS API integration."""

from typing import Any
import requests


# deSEC zone name (external): managed at desec.io
# Per spec, use abhaile.dedyn.io
ZONE = "abhaile.dedyn.io"


def fetch_current(token: str) -> list[dict[str, Any]]:
    """Fetch current DNS records from deSEC API.

    Args:
        token: deSEC API token

    Returns:
        List of current DNS records

    Raises:
        requests.RequestException: If API call fails
    """
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }

    url = f"https://desec.io/api/v1/domains/{ZONE}/rrsets/"

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    rrsets = response.json()

    # Convert to simpler format
    records = []
    for rrset in rrsets:
        records.append(
            {
                "name": rrset.get("subname", "@"),
                "type": rrset["type"],
                "content": rrset["records"],
                "ttl": rrset["ttl"],
            }
        )

    return records


def update_record(
    token: str,
    name: str,
    rtype: str,
    content: list[str],
    ttl: int = 3600,
) -> None:
    """Update or create a DNS record at deSEC.

    Args:
        token: deSEC API token
        name: Record name (use "" or "@" for zone apex)
        rtype: Record type (A, AAAA, CNAME, etc.)
        content: List of record values
        ttl: TTL in seconds

    Raises:
        requests.RequestException: If API call fails
    """
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }

    subname = name if name and name != "@" else ""

    url = f"https://desec.io/api/v1/domains/{ZONE}/rrsets/"

    data = {
        "subname": subname,
        "type": rtype,
        "records": content,
        "ttl": ttl,
    }

    # Use PUT for create-or-update
    response = requests.put(url, headers=headers, json=data, timeout=30)
    response.raise_for_status()


def delete_record(token: str, name: str, rtype: str) -> None:
    """Delete a DNS record from deSEC.

    Args:
        token: deSEC API token
        name: Record name
        rtype: Record type

    Raises:
        requests.RequestException: If API call fails
    """
    headers = {
        "Authorization": f"Token {token}",
    }

    subname = name if name and name != "@" else ""

    url = f"https://desec.io/api/v1/domains/{ZONE}/rrsets/{subname}/{rtype}/"

    response = requests.delete(url, headers=headers, timeout=30)
    response.raise_for_status()
