"""Service composition resolution utilities."""

from pathlib import Path
from typing import Any

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError


def walk_service_includes(
    service_name: str,
    config_root: Path,
    *,
    visited: set[str] | None = None,
    stack: list[str] | None = None,
    cycle_label: str = "Service include cycle detected",
) -> list[str]:
    """Return depth-first include order for a service.

    Includes are returned before the service itself. Services are deduped based
    on the visited set.
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
    ordered: list[str] = []

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
    services: list[str],
    config_root: Path,
    *,
    cycle_label: str = "Service include cycle detected",
) -> list[str]:
    """Return service include order for a mapping-ordered list of services.

    Order rule: iterate services in the provided mapping order, and for each
    service, traverse includes depth-first (includes before the service).
    Services are deduped across the entire mapping order using a shared
    visited set.
    """
    ordered: list[str] = []
    visited: set[str] = set()

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


def walk_host_includes(
    host: str,
    config_root: Path,
    *,
    visited: set[str] | None = None,
    stack: list[str] | None = None,
) -> list[str]:
    """Return depth-first include order for host composition."""
    if visited is None:
        visited = set()
    if stack is None:
        stack = []

    if host in stack:
        cycle = " -> ".join(stack + [host])
        raise RenderError(f"Host include cycle detected: {cycle}")
    if host in visited:
        return []

    host_path = config_root / "hosts" / host / "host.yaml"
    if not host_path.exists():
        raise RenderError(f"Missing host definition: {host_path}")

    host_data = read_yaml_mapping(host_path)
    composition = host_data.get("composition", {}) or {}
    includes = composition.get("include", []) or []
    if not isinstance(includes, list) or any(not isinstance(item, str) for item in includes):
        raise RenderError(f"Host includes must be a list of strings: {host_path}")

    ordered: list[str] = []
    stack.append(host)
    for include_host in includes:
        ordered.extend(
            walk_host_includes(
                include_host,
                config_root,
                visited=visited,
                stack=stack,
            )
        )
    stack.pop()

    visited.add(host)
    ordered.append(host)
    return ordered


def resolve_composition(
    service_name: str,
    config_root: Path,
    merge_strategy: str = "deep",
) -> dict[str, Any]:
    """Resolve full composition for a service including includes.

    Args:
       merge_strategy: "deep" for recursive merge, "shallow" for top-level only.
    """
    ordered_services = walk_service_includes(
        service_name,
        config_root,
        visited=set(),
        stack=[],
        cycle_label="Circular dependency",
    )

    merged: dict[str, Any] = {}
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


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dicts, overlay takes precedence. Lists are replaced, not appended."""
    result = dict(base)
    for key, value in overlay.items():
        if value is None:
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
