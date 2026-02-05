"""Service configuration renderer for service compositions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

import re

from renderers.config import render_config_entries
from utils.config import read_yaml
from utils.errors import RenderError


def render_service_configs(
    host: str,
    services: List[str],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render per-service configuration files for a host.

    Args:
        host: Host name (e.g., phobos, deimos).
        services: Services mapped to the host.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_dir: Path to rendered services root (rendered/services).

    Raises:
        RenderError: If service definitions are missing or rendering fails.
    """
    if not services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    for service in sorted(services):
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        config_entries = _collect_service_config_entries(
            service, services_root, visited=set(), stack=[]
        )

        if not config_entries:
            continue

        service_output_dir = output_dir / service
        context = {
            "network": network,
            "host_name": host,
            "service_name": service,
        }

        resolved_entries = _resolve_config_entry_variables(config_entries, network)

        render_config_entries(
            resolved_entries,
            services_root,
            services_root,
            service_output_dir,
            context,
        )


def _collect_service_config_entries(
    service: str,
    services_root: Path,
    visited: Set[str],
    stack: List[str],
) -> List[Dict[str, Any]]:
    """Collect config entries for a service and its includes.

    Includes are resolved depth-first; included entries are rendered before the
    service's own entries to allow later overrides.
    """
    if service in stack:
        cycle = " -> ".join(stack + [service])
        raise RenderError(f"Service include cycle detected: {cycle}")
    if service in visited:
        return []

    service_yaml = services_root / service / "service.yaml"
    if not service_yaml.exists():
        raise RenderError(f"Missing service definition: {service_yaml}")

    service_data = read_yaml(service_yaml) or {}
    composition = service_data.get("composition", {})

    stack.append(service)

    entries: List[Dict[str, Any]] = []
    includes = composition.get("include", []) or []
    for included in includes:
        entries.extend(
            _collect_service_config_entries(
                included, services_root, visited=visited, stack=stack
            )
        )

    entries.extend(composition.get("config", []) or [])

    stack.pop()
    visited.add(service)
    return entries


def _resolve_config_entry_variables(
    entries: List[Dict[str, Any]],
    network: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Resolve %%...%% placeholders in template variables using network data."""
    resolved: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            resolved.append(entry)
            continue

        source = entry.get("source")
        if not isinstance(source, dict):
            resolved.append(entry)
            continue

        variables = source.get("variables", {})
        if not isinstance(variables, dict):
            resolved.append(entry)
            continue

        resolved_vars = {
            key: _resolve_placeholder_value(value, network)
            for key, value in variables.items()
        }

        updated = dict(entry)
        updated_source = dict(source)
        updated_source["variables"] = resolved_vars
        updated["source"] = updated_source
        resolved.append(updated)

    return resolved


_PLACEHOLDER_PATTERN = re.compile(r"%%(.*?)%%")


def _resolve_placeholder_value(value: Any, network: Dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        parts = [part.strip() for part in expression.split("|") if part.strip()]
        if not parts:
            raise RenderError("Empty placeholder expression")

        current = _lookup_network_value(parts[0], network)
        for part in parts[1:]:
            if part == "strip_cidr":
                current = _strip_cidr(str(current))
            else:
                raise RenderError(f"Unknown placeholder filter: {part}")
        return str(current)

    return _PLACEHOLDER_PATTERN.sub(_replace, value)


def _lookup_network_value(path_expr: str, network: Dict[str, Any]) -> Any:
    if not path_expr.startswith("network."):
        raise RenderError(f"Unsupported placeholder root: {path_expr}")

    current: Any = network
    for key in path_expr.split(".")[1:]:
        if not isinstance(current, dict) or key not in current:
            raise RenderError(f"Placeholder path not found: {path_expr}")
        current = current[key]
    return current


def _strip_cidr(address: str) -> str:
    if "/" not in address:
        return address
    return address.split("/", 1)[0]
