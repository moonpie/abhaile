"""Ingress renderer for aggregating Caddy configuration blocks."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set

from utils.config import read_yaml
from utils.errors import RenderError


def render_ingress_configs(
    host: str,
    host_services: List[str],
    all_services: List[str],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render aggregated ingress configurations for Caddy services.

    Finds base ingress services (those with ingress.{zone}.base) on the current host,
    then aggregates ingress blocks from ALL services in the mapping (across all hosts)
    into the base Caddyfile.

    Args:
        host: Host name (e.g., phobos, deimos).
        host_services: Services mapped to this specific host.
        all_services: All services from the entire mapping (all hosts), in mapping order.
        config_root: Path to config/ directory.
        output_dir: Path to rendered services root (rendered/services).

    Raises:
        RenderError: If rendering fails or validation errors occur.
    """
    if not all_services or not host_services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find base ingress services and their zones (only on this host)
    base_services = _find_base_ingress_services(services_root, host_services)

    # For each base service, aggregate blocks and render
    for base_service, zones in base_services.items():
        service_yaml = services_root / base_service / "service.yaml"
        service_data = read_yaml(service_yaml) or {}

        ingress_def = service_data.get("composition", {}).get("ingress", {})

        for zone in zones:
            zone_def = ingress_def.get(zone, {})
            base = zone_def.get("base")

            if not base:
                raise RenderError(
                    f"Service '{base_service}' missing ingress.{zone}.base definition"
                )

            source = base.get("source")
            destination = base.get("destination")

            if not source or not destination:
                raise RenderError(
                    f"Service '{base_service}' ingress.{zone}.base missing source or destination"
                )

            # Read base Caddyfile
            # Source path may be relative to service dir or include service name prefix
            base_path = services_root / base_service / source
            if not base_path.exists():
                # Try without service prefix (source might be service-name/path)
                if source.startswith(f"{base_service}/"):
                    relative_source = source[len(base_service) + 1 :]
                    base_path = services_root / base_service / relative_source

            if not base_path.exists():
                raise RenderError(
                    f"Base Caddyfile not found: {source} in service '{base_service}'"
                )

            base_content = base_path.read_text()

            # Collect blocks from all services (mapping order)
            blocks = _collect_ingress_blocks(zone, all_services, services_root)

            # Aggregate: base + sorted blocks
            aggregated = _aggregate_caddyfile(base_content, blocks)

            # Write to output
            output_path = output_dir / base_service / destination.lstrip("/")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(aggregated)


def _find_base_ingress_services(
    services_root: Path,
    all_services: List[str],
) -> Dict[str, List[str]]:
    """Find services that define ingress base configurations.

    Args:
        services_root: Path to config/services directory.
        all_services: All services from mapping.

    Returns:
        Dict mapping service name to list of zones (e.g., {'caddy-dmz': ['dmz']}).

    Raises:
        RenderError: If service.yaml is missing or invalid.
    """
    base_services: Dict[str, List[str]] = {}

    for service in all_services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        ingress_def = service_data.get("composition", {}).get("ingress", {})

        if not ingress_def:
            continue

        zones = []
        for zone in ["dmz", "internal"]:
            zone_def = ingress_def.get(zone, {})
            if "base" in zone_def:
                zones.append(zone)

        if zones:
            base_services[service] = zones

    return base_services


def _collect_ingress_blocks(
    zone: str,
    all_services: List[str],
    services_root: Path,
) -> List[tuple[str, str]]:
    """Collect ingress blocks for a specific zone from all services.

    Recursively follows composition.include to collect blocks from included services.

    Args:
        zone: Ingress zone name (dmz or internal).
        all_services: All services from mapping.
        services_root: Path to config/services directory.

    Returns:
        List of (service_name, block_content) tuples in mapping order.

    Raises:
        RenderError: If a referenced block file doesn't exist.
    """
    blocks: List[tuple[str, str]] = []
    visited: Set[str] = set()

    for service in all_services:
        blocks.extend(
            _collect_service_ingress_blocks(
                service=service,
                zone=zone,
                services_root=services_root,
                visited=visited,
                stack=[],
            )
        )

    return blocks


def _collect_service_ingress_blocks(
    service: str,
    zone: str,
    services_root: Path,
    visited: Set[str],
    stack: List[str],
) -> List[tuple[str, str]]:
    """Recursively collect ingress blocks from a service and its includes.

    Args:
        service: Service name.
        zone: Ingress zone name (dmz or internal).
        services_root: Path to config/services directory.
        visited: Set of already-visited services.
        stack: Current include stack for cycle detection.

    Returns:
        List of (service_name, block_content) tuples.

    Raises:
        RenderError: If cycle detected or block file not found.
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
    blocks: List[tuple[str, str]] = []

    # First, recursively collect from includes
    includes = composition.get("include", []) or []
    for included in includes:
        blocks.extend(
            _collect_service_ingress_blocks(
                service=included,
                zone=zone,
                services_root=services_root,
                visited=visited,
                stack=stack,
            )
        )

    # Then, collect from this service's ingress definition
    ingress_def = composition.get("ingress", {})
    zone_def = ingress_def.get(zone, {})
    block_paths = zone_def.get("blocks", []) or []

    for block_path in block_paths:
        # Block path may be relative to service dir or include service name prefix
        full_path = services_root / service / block_path
        if not full_path.exists():
            # Try without service prefix (block_path might be service-name/path)
            if block_path.startswith(f"{service}/"):
                relative_path = block_path[len(service) + 1 :]
                full_path = services_root / service / relative_path

        if not full_path.exists():
            raise RenderError(
                f"Ingress block not found: {block_path} in service '{service}'"
            )

        block_content = full_path.read_text()
        blocks.append((service, block_content))

    stack.pop()
    visited.add(service)
    return blocks


def _aggregate_caddyfile(base_content: str, blocks: List[tuple[str, str]]) -> str:
    """Aggregate base Caddyfile with ingress blocks.

    Args:
        base_content: Content of the base Caddyfile.
        blocks: List of (service_name, block_content) tuples.

    Returns:
        Aggregated Caddyfile content.
    """
    if not blocks:
        return base_content

    # Build aggregated content
    parts = [base_content]

    # Ensure base ends with newline
    if not base_content.endswith("\n"):
        parts.append("\n")

    # Add comment separator and blocks
    parts.append("\n# ========== Aggregated Ingress Blocks ==========\n")

    for service_name, block_content in blocks:
        parts.append(f"\n# --- {service_name} ---\n")
        parts.append(block_content)

        # Ensure block ends with newline
        if not block_content.endswith("\n"):
            parts.append("\n")

    return "".join(parts)
