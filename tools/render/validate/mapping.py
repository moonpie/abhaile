"""Mapping configuration validation.

Validates mapping.yaml host references and service assignments.
"""

from __future__ import annotations

from typing import Any

from tools.common.core import ValidationError


def validate_mapping_hosts(
    mapping: dict[str, Any], network: dict[str, Any]
) -> list[str]:
    """Validate that hosts in mapping.yaml exist in network.yaml.

    Args:
        mapping: Parsed mapping.yaml content
        network: Parsed network.yaml content

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []
    hosts_defined = set((network.get("hosts") or {}).keys())

    for host_entry in mapping.get("abhaile", []):
        if isinstance(host_entry, dict):
            for hostname, svc_list in host_entry.items():
                if hostname not in hosts_defined:
                    errors.append(
                        f"Mapping references unknown host '{hostname}' (not in network.yaml hosts)"
                    )
                if not isinstance(svc_list, list):
                    errors.append(
                        f"Expected list of services for host '{hostname}' in mapping.yaml"
                    )

    return errors


def validate_host_mapping(mapping: dict[str, Any], hostname: str) -> list[str]:
    """Return services mapped to host or raise if none.

    Raises RenderError if the host is not present or has no services.
    """
    host_services: list[str] = []
    for host_entry in mapping.get("abhaile", []):
        if isinstance(host_entry, dict) and hostname in host_entry:
            host_services = host_entry[hostname]
            break

    if not host_services:
        raise ValidationError(
            f"Host '{hostname}' not found in mapping.yaml or has no services assigned. "
            f"Add the host to config/mapping.yaml before rendering."
        )

    return host_services
