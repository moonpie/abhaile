"""Service configuration validation.

Validates service.yaml files, templates, and network requirements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.core import load_yaml
from tools.render.validate.errors import ValidationError


def validate_template_sources(services_dir: Path, service_names: set[str]) -> list[str]:
    """Validate that referenced templates and config sources exist.

    Args:
        services_dir: Base services directory (config/services)
        service_names: Set of service names to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    for service_name in service_names:
        service_path = services_dir / service_name
        service_yaml = service_path / "service.yaml"

        # Skip if service.yaml doesn't exist (will be caught elsewhere)
        if not service_yaml.exists():
            continue

        service_config = load_yaml(service_yaml)

        # Validate config sources
        for cfg_item in service_config.get("config", []):
            source = cfg_item.get("source")
            if not source:
                continue

            if isinstance(source, str):
                # Static file reference
                # Paths in service.yaml always include service prefix: servicename/path/to/file
                # Strip the service name to get path relative to service directory
                source_path = Path(source)

                # Validate first component matches service name
                if not source_path.parts or source_path.parts[0] != service_name:
                    errors.append(
                        f"Service '{service_name}' config source must start with service name: {source}"
                    )
                    continue

                # Get path relative to service directory (strip service name prefix)
                relative_path = Path(*source_path.parts[1:])
                source_file = service_path / relative_path
                if not source_file.exists():
                    errors.append(
                        f"Service '{service_name}' config references missing file: {source}"
                    )
            elif isinstance(source, dict) and "template" in source:
                # Template reference - may reference a shared template
                template_rel = source["template"]

                # Check if it's a service-local template first
                service_local_template = service_path / template_rel
                if service_local_template.exists():
                    continue

                # Otherwise check if it's a shared template across services
                shared_template = services_dir / template_rel
                if not shared_template.exists():
                    errors.append(
                        f"Service '{service_name}' config references missing template: {template_rel}"
                    )

        # Validate Vault Agent templates
        vault_agent = service_config.get("vault_agent", {})
        for tmpl in vault_agent.get("templates", []):
            tmpl_source = tmpl.get("source")
            if tmpl_source:
                # Paths in vault_agent.templates always include service prefix
                tmpl_path = Path(tmpl_source)

                # Validate first component matches service name
                if not tmpl_path.parts or tmpl_path.parts[0] != service_name:
                    errors.append(
                        f"Service '{service_name}' vault_agent source must start with service name: {tmpl_source}"
                    )
                    continue

                # Get path relative to service directory (strip service name prefix)
                relative_path = Path(*tmpl_path.parts[1:])
                tmpl_file = service_path / relative_path
                if not tmpl_file.exists():
                    errors.append(
                        f"Service '{service_name}' vault_agent references missing template: {tmpl_source}"
                    )

    return errors


def validate_service_network_requirements(
    service_name: str,
    service_config: dict[str, Any],
    network_config: dict[str, Any],
) -> None:
    """Validate service network requirements against network.yaml.

    Args:
        service_name: Name of the service
        service_config: Parsed service.yaml content
        network_config: Parsed network.yaml content

    Raises:
        ValidationError: If network requirements are not met
    """
    network_mode = service_config.get("network", "host")

    # host network mode has no requirements
    if network_mode == "host":
        return

    # service-32 and ipvlan-l2 modes require network.yaml entry
    services_in_network = network_config.get("services") or {}
    if service_name not in services_in_network:
        raise ValidationError(
            f"Service '{service_name}' uses network mode '{network_mode}' but has no entry in network.yaml services section"
        )

    svc_net = services_in_network[service_name]
    if "address" not in svc_net:
        raise ValidationError(
            f"Service '{service_name}' in network.yaml missing required 'address' field"
        )
    if "vlan" not in svc_net:
        raise ValidationError(
            f"Service '{service_name}' in network.yaml missing required 'vlan' field"
        )

    # Validate VLAN exists
    vlan_name = svc_net["vlan"]
    vlans_defined = network_config.get("vlans") or {}
    if vlan_name not in vlans_defined:
        raise ValidationError(
            f"Service '{service_name}' references VLAN '{vlan_name}' not defined in network.yaml"
        )


def validate_required_container_vlans(
    hostname: str,
    services: list[tuple[str, dict[str, Any]]],
    network_config: dict[str, Any],
) -> None:
    """Validate that host has required ipvlan interfaces for container services.

    Args:
        hostname: Name of the host
        services: List of (service_name, service_config) tuples
        network_config: Parsed network.yaml content

    Raises:
        ValidationError: If host is missing required ipvlan interfaces
    """
    host_config = (network_config.get("hosts") or {}).get(hostname, {})
    host_interfaces = set(host_config.get("interfaces", []))

    for svc_name, svc_cfg in services:
        svc_type = svc_cfg.get("type")
        network_mode = svc_cfg.get("network", "host")

        # Only container/pod types with ipvlan-l2 need interface validation
        if svc_type not in ("container", "pod") or network_mode != "ipvlan-l2":
            continue

        # Get VLAN for this service
        services_in_network = network_config.get("services") or {}
        if svc_name not in services_in_network:
            continue  # Already caught by validate_service_network_requirements

        svc_net = services_in_network[svc_name]
        vlan_name = svc_net.get("vlan")
        if not vlan_name:
            continue

        # Get VLAN ID
        vlans_defined = network_config.get("vlans") or {}
        vlan_config = vlans_defined.get(vlan_name, {})
        vlan_id = vlan_config.get("id")

        # Determine required interface name
        if vlan_id == 20:
            required_iface = "ipvlan-l2"
        else:
            required_iface = f"ipvlan-l2.{vlan_id}"

        if required_iface not in host_interfaces:
            raise ValidationError(
                f"Service '{svc_name}' on host '{hostname}' requires interface '{required_iface}' "
                f"but host only has: {', '.join(sorted(host_interfaces))}"
            )
