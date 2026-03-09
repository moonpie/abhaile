"""Service composition resolution utilities."""

from pathlib import Path
from typing import Any, Dict, List, Set

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError


def walk_service_includes(
    service_name: str,
    config_root: Path,
    *,
    visited: Set[str] | None = None,
    stack: List[str] | None = None,
    cycle_label: str = "Service include cycle detected",
) -> List[str]:
    """Return depth-first include order for a service.

    Includes are returned before the service itself. Services are deduped based
    on the visited set.

    Args:
        service_name: Name of the service to traverse.
        config_root: Path to config/ directory.
        visited: Optional shared visited set for dedupe across roots.
        stack: Optional shared stack for cycle detection.
        cycle_label: Error label used when a cycle is detected.

    Returns:
        Ordered list of services (includes first, then service).

    Raises:
        RenderError: If a cycle is detected or a service is missing.
    """
    if visited is None:
        visited = set()
    if stack is None:
        stack = []

    if service_name in stack:
        cycle = " -> ".join(stack + [service_name])
        raise RenderError(f"{cycle_label}: {cycle}")
    if service_name in visited:
        return []

    service_path = config_root / "services" / service_name / "service.yaml"
    if not service_path.exists():
        raise RenderError(f"Missing service definition: {service_path}")

    service_data = read_yaml_mapping(service_path)
    composition = service_data.get("composition", {}) or {}

    stack.append(service_name)
    ordered: List[str] = []

    includes = composition.get("include", []) or []
    for included in includes:
        ordered.extend(
            walk_service_includes(
                included,
                config_root,
                visited=visited,
                stack=stack,
                cycle_label=cycle_label,
            )
        )

    stack.pop()
    visited.add(service_name)
    ordered.append(service_name)
    return ordered


def walk_mapping_includes(
    services: List[str],
    config_root: Path,
    *,
    cycle_label: str = "Service include cycle detected",
) -> List[str]:
    """Return service include order for a mapping-ordered list of services.

    Order rule: iterate services in the provided mapping order, and for each
    service, traverse includes depth-first (includes before the service).
    Services are deduped across the entire mapping order using a shared
    visited set.

    Args:
        services: Services from mapping in mapping order.
        config_root: Path to config/ directory.
        cycle_label: Error label used when a cycle is detected.

    Returns:
        Ordered list of services (includes first, then service), respecting
        mapping order and depth-first include traversal with dedupe.
    """
    ordered: List[str] = []
    visited: Set[str] = set()

    for service in services:
        ordered.extend(
            walk_service_includes(
                service,
                config_root,
                visited=visited,
                stack=[],
                cycle_label=cycle_label,
            )
        )

    return ordered


def resolve_composition(
    service_name: str,
    config_root: Path,
    merge_strategy: str = "deep",
) -> Dict[str, Any]:
    """Resolve full composition for a service including includes.

    Args:
       service_name: Name of the service to resolve.
       config_root: Path to config/ directory.
       merge_strategy: "deep" for recursive merge, "shallow" for top-level only.

    Returns:
        Fully resolved composition dict.

    Raises:
        RenderError: If circular dependency detected or service missing.
    """
    ordered_services = walk_service_includes(
        service_name,
        config_root,
        visited=set(),
        stack=[],
        cycle_label="Circular dependency",
    )

    merged: Dict[str, Any] = {}
    for name in ordered_services:
        service_path = config_root / "services" / name / "service.yaml"
        if not service_path.exists():
            raise RenderError(f"Service not found: {service_path}")

        service_data = read_yaml_mapping(service_path)
        composition = service_data.get("composition", {}) or {}
        own_comp = {k: v for k, v in composition.items() if k != "include"}

        if merge_strategy == "deep":
            merged = _deep_merge(merged, own_comp)
        else:
            merged.update(own_comp)

    return merged


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dicts, overlay takes precedence."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
