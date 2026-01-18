"""High-level validation orchestration.

Coordinates validation across mapping, network, and service configurations.
"""

from __future__ import annotations

from typing import Any

from tools.common.core import load_yaml, PathConfig
from tools.render.validate.errors import ValidationError
from tools.render.validate.mapping import (
    validate_mapping_hosts,
)
from tools.render.validate.network import (
    validate_network_uniqueness,
)
from tools.render.validate.service import (
    validate_required_container_vlans,
    validate_service_network_requirements,
    validate_template_sources,
)


def validate_all(paths: PathConfig) -> list[str]:
    """Run all validation checks and return errors.

    Args:
        paths: PathConfig instance with config/output paths

    Returns:
        List of all validation errors (empty if all valid)
    """
    errors: list[str] = []

    # Determine paths from PathConfig
    config_dir = paths.config_root
    mapping_path = config_dir / "mapping.yaml"
    network_path = config_dir / "network.yaml"

    # Load configs
    mapping = load_yaml(mapping_path)
    network = load_yaml(network_path)

    # Validate mapping hosts
    errors.extend(validate_mapping_hosts(mapping, network))

    # Validate network uniqueness (last octets)
    errors.extend(validate_network_uniqueness(network))

    # Validate services
    services_dir = config_dir / "services"

    # Collect all service names
    all_services = set()
    for host_entry in mapping.get("abhaile", []):
        if not isinstance(host_entry, dict):
            continue

        for hostname, service_list in host_entry.items():
            if not isinstance(service_list, list):
                continue
            all_services.update(service_list)

    # Validate template sources for all services
    errors.extend(validate_template_sources(services_dir, all_services))

    # Validate network requirements and container VLANs per host
    for host_entry in mapping.get("abhaile", []):
        if not isinstance(host_entry, dict):
            continue

        for hostname, service_list in host_entry.items():
            if not isinstance(service_list, list):
                continue

            # Collect service configs
            services: list[tuple[str, dict[str, Any]]] = []
            for svc_name in service_list:
                svc_yaml = services_dir / svc_name / "service.yaml"
                if not svc_yaml.exists():
                    errors.append(
                        f"Service '{svc_name}' mapped to host '{hostname}' but {svc_yaml} does not exist"
                    )
                    continue

                svc_cfg = load_yaml(svc_yaml)
                services.append((svc_name, svc_cfg))

                # Validate network requirements
                try:
                    validate_service_network_requirements(svc_name, svc_cfg, network)
                except ValidationError as e:
                    errors.append(str(e))

            # Validate container VLAN requirements for this host
            try:
                validate_required_container_vlans(hostname, services, network)
            except ValidationError as e:
                errors.append(str(e))

    return errors


def validate_or_raise(paths: PathConfig) -> None:
    """Run all validation checks and raise on first error.

    Args:
        paths: PathConfig instance with config/output paths

    Raises:
        ValidationError: If any validation check fails
    """
    errors = validate_all(paths)
    if errors:
        raise ValidationError(
            f"Configuration validation failed with {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
