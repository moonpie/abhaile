"""Network configuration validation.

Validates network.yaml structure, service address uniqueness, and last-octet conflicts.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from tools.common.core import load_yaml, get_logger
from tools.common.core.context_utils import last_octet
from tools.render.validate.errors import ValidationError

logger = get_logger(__name__)


def validate_last_octet_uniqueness(network: dict[str, Any]) -> None:
    """Validate that last octets are unique per VLAN for drop-in ordering.

    This ensures that when we create drop-in files like 010-service.conf,
    there are no conflicts within the same VLAN.

    Args:
        network: Network configuration dictionary

    Raises:
        ValidationError: If duplicate last octets found in same VLAN
    """
    services = network.get("services", {})

    # Group services by VLAN and collect their last octets
    vlan_octets: dict[str, dict[int, list[str]]] = {}

    for svc_name, svc_data in services.items():
        address = svc_data.get("address")
        vlan = svc_data.get("vlan")

        if not address or not vlan:
            continue

        octet = last_octet(address)

        if vlan not in vlan_octets:
            vlan_octets[vlan] = {}
        if octet not in vlan_octets[vlan]:
            vlan_octets[vlan][octet] = []

        vlan_octets[vlan][octet].append(svc_name)

    # Check for duplicates
    has_duplicates = False
    for vlan, octets in vlan_octets.items():
        for octet, services_list in octets.items():
            if len(services_list) > 1:
                logger.error(
                    "VLAN '%s' has duplicate last octet %s for services: %s",
                    vlan,
                    octet,
                    ", ".join(services_list),
                )
                has_duplicates = True

    if has_duplicates:
        raise ValidationError(
            "Duplicate last-octet values detected in network services"
        )


def validate_network_config(network_or_path):
    """Validate network configuration structure.

    Accepts either a loaded dict or a Path to a directory containing network.yaml.

    Args:
        network_or_path: Either a dict or Path to config directory.

    Raises:
        ValidationError: If network.yaml structure is invalid.
    """
    if isinstance(network_or_path, (str, Path)):
        base = Path(network_or_path)
        yaml_path = base / "network.yaml"
        if not yaml_path.exists():
            raise ValidationError(f"network.yaml not found at {yaml_path}")
        data = load_yaml(yaml_path)
    elif isinstance(network_or_path, dict):
        data = network_or_path
    else:
        raise ValidationError(
            f"Expected dict or Path, got {type(network_or_path).__name__}"
        )

    if "vlans" not in data:
        raise ValidationError("network.yaml missing required 'vlans' key")

    for vlan_name, vlan_data in data["vlans"].items():
        # Accept either 'cidr' or legacy 'subnet'
        if "cidr" not in vlan_data and "subnet" not in vlan_data:
            raise ValidationError(
                f"VLAN '{vlan_name}' missing 'cidr' or 'subnet' field"
            )

    services = data.get("services", {})
    if not services:
        raise ValidationError("network.yaml has no services defined")

    seen_ips = set()
    for svc_name, svc_def in services.items():
        addr = svc_def.get("address")
        vlan_key = svc_def.get("vlan")
        if addr and vlan_key:
            vlan_data = data["vlans"].get(vlan_key) or next(
                (v for k, v in data["vlans"].items() if k == vlan_key), None
            )
            if not vlan_data:
                raise ValidationError(
                    f"Service '{svc_name}' references undefined VLAN '{vlan_key}'"
                )
            try:
                ip = ipaddress.ip_interface(addr).ip
                subnet = vlan_data.get("cidr") or vlan_data.get("subnet")
                network = ipaddress.ip_network(subnet, strict=False)
                if ip not in network:
                    raise ValidationError(
                        f"Service '{svc_name}' address {addr} not in VLAN subnet {subnet}"
                    )
                if str(ip) in seen_ips:
                    raise ValidationError(
                        f"Service '{svc_name}' has duplicate IP address {ip}"
                    )
                seen_ips.add(str(ip))
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    f"Service '{svc_name}' has invalid address '{addr}': {e}"
                ) from e


def validate_network_uniqueness(network: dict[str, Any]) -> list[str]:
    """Validate service IP address last-octet uniqueness.

    Args:
        network: Parsed network.yaml content

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []
    try:
        validate_last_octet_uniqueness(network)
    except Exception as e:
        errors.append(str(e))
    return errors
