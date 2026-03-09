"""Service configuration validation: names, references, existence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError


def parse_mapping(mapping: Any) -> Dict[str, List[str]]:
    """Parse mapping.yaml to extract host -> services mapping.

    Args:
        mapping: Mapping configuration data.

    Returns:
        Dictionary mapping host names to lists of service names.

    Raises:
        RenderError: If mapping structure is invalid.
    """
    if not isinstance(mapping, dict) or "abhaile" not in mapping:
        raise RenderError("mapping.yaml missing top-level 'abhaile' list")
    hosts: Dict[str, List[str]] = {}
    for item in mapping["abhaile"]:
        if not isinstance(item, dict) or len(item) != 1:
            raise RenderError("mapping.yaml host entries must be single-key objects")
        host, services = next(iter(item.items()))
        if not isinstance(services, list):
            raise RenderError(f"mapping.yaml services for host '{host}' must be a list")
        service_names: List[str] = []
        for svc in services:
            if isinstance(svc, str):
                service_names.append(svc)
            elif isinstance(svc, dict):
                if "name" in svc and isinstance(svc["name"], str):
                    service_names.append(svc["name"])
                elif len(svc) == 1:
                    service_names.append(next(iter(svc.keys())))
                else:
                    raise RenderError(
                        f"mapping.yaml service entries for host '{host}' must be string or single-key object"
                    )
            else:
                raise RenderError(
                    f"mapping.yaml service entries for host '{host}' must be string or object"
                )
        hosts[host] = service_names
    return hosts


def get_all_services_in_order(mapping: dict[str, Any]) -> list[str]:
    """Extract all unique services in mapping order.

    Args:
        mapping: Mapping configuration data.

    Returns:
        List of service names in declaration order (deduplicated).

    Raises:
        RenderError: If mapping structure is invalid.
    """
    if not isinstance(mapping, dict) or "abhaile" not in mapping:
        raise RenderError("mapping.yaml missing top-level 'abhaile' list")

    seen: set[str] = set()
    ordered: list[str] = []

    for item in mapping["abhaile"]:
        if not isinstance(item, dict) or len(item) != 1:
            raise RenderError("mapping.yaml host entries must be single-key objects")

        _, services = next(iter(item.items()))
        if not isinstance(services, list):
            raise RenderError("mapping.yaml services must be a list")

        for svc_entry in services:
            name = _extract_service_name(svc_entry)
            if name not in seen:
                ordered.append(name)
                seen.add(name)

    return ordered


def _extract_service_name(svc_entry: Any) -> str:
    """Extract service name from mapping entry."""
    if isinstance(svc_entry, str):
        return svc_entry
    if isinstance(svc_entry, dict):
        if "name" in svc_entry and isinstance(svc_entry["name"], str):
            return svc_entry["name"]
        if len(svc_entry) == 1:
            name = next(iter(svc_entry.keys()))
            if isinstance(name, str):
                return name
    raise RenderError(f"Invalid service entry: {svc_entry}")


def ensure_service_definitions(config_root: Path, services: Iterable[str]) -> List[Path]:
    """Ensure all services have service.yaml files.

    Args:
        config_root: Path to config/ directory.
        services: Service names to check.

    Returns:
        List of service.yaml paths.

    Raises:
        RenderError: If any service definition is missing.
    """
    service_paths: List[Path] = []
    for service in services:
        service_file = config_root / "services" / service / "service.yaml"
        if not service_file.exists():
            raise RenderError(f"Missing service definition: {service_file}")
        service_paths.append(service_file)
    return service_paths


def validate_service_names(config_root: Path) -> None:
    """Validate that service name matches directory name.

    Args:
        config_root: Path to config/ directory.

    Raises:
        RenderError: If any service name mismatches.
    """
    errors: List[str] = []
    for service_yaml in (config_root / "services").glob("*/service.yaml"):
        service_data = read_yaml_mapping(service_yaml)
        name = service_data.get("name")
        if name and name != service_yaml.parent.name:
            errors.append(f"Service name mismatch: {service_yaml} has name '{name}'")

    if errors:
        formatted = "\n".join(f"- {err}" for err in errors)
        raise RenderError(f"Service name validation failed:\n{formatted}")
