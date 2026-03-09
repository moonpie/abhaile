"""Service configuration renderer for service compositions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from abhaile.renderers.config import render_config_entries
from abhaile.utils.composition import walk_service_includes
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError
from abhaile.utils.placeholders import resolve_placeholders


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

    for service in services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        config_entries = _collect_service_config_entries(service, config_root)

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
    config_root: Path,
) -> List[Dict[str, Any]]:
    """Collect config entries for a service and its includes.

    Includes are resolved depth-first; included entries are rendered before the
    service's own entries to allow later overrides.
    """
    entries: List[Dict[str, Any]] = []
    ordered_services = walk_service_includes(service, config_root)

    for service_name in ordered_services:
        service_yaml = config_root / "services" / service_name / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        composition = service_data.get("composition", {})
        entries.extend(composition.get("config", []) or [])

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

        resolved_vars = resolve_placeholders(variables, network)

        updated = dict(entry)
        updated_source = dict(source)
        updated_source["variables"] = resolved_vars
        updated["source"] = updated_source
        resolved.append(updated)

    return resolved
