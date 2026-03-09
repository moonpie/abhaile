"""Render DNS zone files from network configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import TemplateError, TemplateNotFound, UndefinedError

from abhaile.dns.records import collect_zone_records
from abhaile.utils.composition import resolve_composition, walk_service_includes
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def render_dns(
    network: dict[str, Any],
    output_dir: Path,
    host_services: list[str],
    all_services: list[str],
    config_root: Path,
) -> None:
    """Render DNS zone files for zones relevant to services on this host.

    Zone files are rendered only to services running on the current host that have
    dns.zone_files configuration (either direct or inherited via composition.include).
    This allows per-host divergence in zone configurations.

    Zone records are aggregated only from services deployed in mapping.yaml (for
    cross-host service discovery), but zones are only rendered to services on the
    current host.

    Args:
        network: Network configuration from network.yaml.
        output_dir: Output directory for rendered zone files.
        host_services: Services running on the current host being rendered.
        all_services: All services from mapping.yaml in mapping order (for zone record aggregation).
        config_root: Config root directory.

    Raises:
        RenderError: If zone rendering fails.
    """
    if "dns" not in network or "zones" not in network["dns"]:
        return

    zones = network["dns"]["zones"]

    # Build map of provider.name -> services that provide zones for that provider
    # Provider services are determined via transitive includes and direct service name matches
    provider_to_services = build_provider_mapping(host_services, config_root)

    for zone in zones:
        zone_name = zone.get("name")
        if not zone_name:
            raise RenderError("Zone missing 'name' field")

        provider = zone.get("provider", {})
        provider_type = provider.get("type")
        provider_name = provider.get("name")

        if not provider_name:
            raise RenderError(f"Zone '{zone_name}' missing 'provider.name'")

        # Only render zones for internal providers (not external DNS providers)
        if provider_type != "internal":
            continue

        # Collect records for this zone (from deployed services in mapping.yaml)
        records = collect_zone_records(zone, network, all_services)

        # Get zone_files configuration from provider service
        zone_files = get_zone_files_config(provider_name, config_root)
        if not zone_files:
            raise RenderError(
                f"Zone '{zone_name}' provider '{provider_name}' has no zone_files config. "
                f"Ensure '{provider_name}' service defines dns.zone_files in its service.yaml "
                f"or via composition.include."
            )

        # Render zone files for each matching entry
        for zone_file_entry in zone_files:
            zone_pattern = zone_file_entry.get("zone", "")

            # Check if this zone matches the pattern (support '*' wildcard)
            if zone_pattern != "*" and zone_name != zone_pattern:
                continue

            file_config = zone_file_entry.get("file", {})
            source_config = file_config.get("source", {})
            template_path = source_config.get("template", "")
            dest_path = file_config.get("destination", "")

            if not template_path or not dest_path:
                raise RenderError(
                    f"Zone '{zone_name}' zone_files entry missing template or destination"
                )

            # Render template with zone context
            zone_content = render_zone_template(template_path, zone, records, config_root)

            # Find services that provide this zone (based on provider.name)
            providing_services = provider_to_services.get(provider_name, [])

            if not providing_services:
                raise RenderError(
                    f"Zone '{zone_name}' has provider '{provider_name}' but no services "
                    f"on this host provide zones for that provider. "
                    f"To fix this: ensure a service on this host either directly defines "
                    f"dns.zone_files (direct provider mode) or includes '{provider_name}' "
                    f"in its composition.include list (transitive provider mode)."
                )

            # Render zone file to each providing service
            for service_name in providing_services:
                # Replace zone.zone placeholder in destination with actual zone name
                zone_name_stripped = zone_name.rstrip(".")
                # Remove leading / from destination if present (should be relative)
                actual_dest = dest_path.lstrip("/")
                # Replace zone.zone placeholder with actual zone name
                actual_dest = actual_dest.replace("zone.zone", f"{zone_name_stripped}.zone")

                zone_output_dir = output_dir / "services" / service_name / Path(actual_dest).parent
                zone_output_dir.mkdir(parents=True, exist_ok=True)

                # Write zone file
                zone_file = zone_output_dir / Path(actual_dest).name
                zone_file.write_text(zone_content, encoding="utf-8")


def build_provider_mapping(
    host_services: list[str],
    config_root: Path,
) -> dict[str, list[str]]:
    """Build map of provider.name -> services that provide zones for that provider.

    Provider services are determined via two mechanisms:
    1. Direct provider mode: A service on this host directly defines dns.zone_files
       and can be referenced by its own service name as a provider.
    2. Transitive provider mode: A service on this host includes a provider service
       in its composition.include chain and has dns.zone_files, making it a provider
       for that included service.

    Args:
        host_services: Services running on the current host.
        config_root: Config root directory.

    Returns:
        Dict mapping provider name to list of services on this host that provide
        zone files for that provider.

    Raises:
        RenderError: If service composition cannot be resolved.
    """
    provider_to_services: dict[str, list[str]] = {}

    for service_name in host_services:
        service_path = config_root / "services" / service_name / "service.yaml"
        if not service_path.exists():
            continue

        # Resolve full composition including inherited configs
        composition = _resolve_service_composition(service_name, config_root)

        # Check if service has dns.zone_files (inherited or direct)
        dns_config = composition.get("dns", {})
        zone_files = dns_config.get("zone_files", [])

        if not zone_files:
            continue

        # This service provides zones. Determine which providers it serves:
        # 1. The service itself (direct provider mode)
        if service_name not in provider_to_services:
            provider_to_services[service_name] = []
        if service_name not in provider_to_services[service_name]:
            provider_to_services[service_name].append(service_name)

        # 2. All services in its include chain (transitive provider mode)
        includes = walk_service_includes(service_name, config_root)
        for included_service in includes:
            if included_service != service_name:  # Avoid duplication with direct mode
                if included_service not in provider_to_services:
                    provider_to_services[included_service] = []
                if service_name not in provider_to_services[included_service]:
                    provider_to_services[included_service].append(service_name)

    return provider_to_services


def _resolve_service_composition(
    service_name: str,
    config_root: Path,
) -> dict[str, Any]:
    """Resolve full composition for a service including inherited configs."""
    return resolve_composition(
        service_name=service_name,
        config_root=config_root,
        merge_strategy="deep",
    )


def get_zone_files_config(
    provider_name: str,
    config_root: Path,
) -> list[dict[str, Any]]:
    """Get zone_files configuration from a provider service.

    Supports both direct and transitive provider modes. The provider service
    may exist as:
    - A service with the given name that defines dns.zone_files directly, or
    - A service that can be included by other services in composition.include

    Args:
        provider_name: Name of the provider service (e.g., coredns, coredns-common).
        config_root: Config root directory.

    Returns:
        List of zone_files entries for the provider service.

    Raises:
        RenderError: If the provider service is missing, has invalid dns.zone_files
            configuration, or if the type of zone_files entries is incorrect.
    """
    provider_path = config_root / "services" / provider_name / "service.yaml"
    if not provider_path.exists():
        raise RenderError(
            f"Missing provider service definition for '{provider_name}' at {provider_path}. "
            f"Ensure the service exists in config/services/ directory and has a service.yaml file."
        )

    try:
        provider_comp = resolve_composition(provider_name, config_root, merge_strategy="deep")
    except RenderError as e:
        raise RenderError(
            f"Failed to resolve composition for provider '{provider_name}': {e}"
        ) from e

    dns_config = provider_comp.get("dns", {})
    if not isinstance(dns_config, dict):
        raise RenderError(
            f"Invalid 'dns' configuration for provider '{provider_name}': "
            f"dns must be a dictionary, got {type(dns_config).__name__}"
        )

    zone_files = dns_config.get("zone_files", [])
    if not isinstance(zone_files, list):
        raise RenderError(
            f"Invalid 'dns.zone_files' for provider '{provider_name}': "
            f"zone_files must be a list, got {type(zone_files).__name__}. "
            f"Define zone_files as: dns:\n  zone_files:\n    - zone: '...'  # Entry objects"
        )

    typed_zone_files: list[dict[str, Any]] = []
    for idx, entry in enumerate(zone_files):
        if not isinstance(entry, dict):
            raise RenderError(
                f"Invalid zone_files entry at index {idx} for provider '{provider_name}': "
                f"each entry must be an object, got {type(entry).__name__}. "
                f"Each entry should have 'zone' and 'file' keys."
            )
        typed_zone_files.append(entry)

    return typed_zone_files


def render_zone_template(
    template_path: str,
    zone: dict[str, Any],
    records: list[dict[str, Any]],
    config_root: Path,
) -> str:
    """Render a zone file from a Jinja2 template.

    Args:
        template_path: Path to template relative to config root (service/path/file.j2).
        zone: Zone configuration dict.
        records: Collected zone records.
        config_root: Config root directory.

    Returns:
        Rendered zone file content.
    """
    # Parse template path - format: service/path/file.j2
    parts = template_path.split("/", 1)
    if len(parts) != 2:
        raise RenderError(f"Invalid template path: {template_path}")

    service_name, rel_path = parts
    service_dir = config_root / "services" / service_name

    # Load template
    env = create_jinja_env(
        service_dir,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    try:
        template = env.get_template(rel_path)
    except (TemplateError, TemplateNotFound) as e:
        raise RenderError(f"Failed to load template {template_path}: {e}")

    # Prepare context for template
    serial_info = zone.get("serial", {})
    if not isinstance(serial_info, dict) or not serial_info:
        raise RenderError("Zone missing serial configuration")

    date_raw = serial_info.get("date")
    counter_raw = serial_info.get("counter")
    if date_raw is None or str(date_raw).strip() == "":
        raise RenderError("Zone serial missing date")
    if counter_raw is None or str(counter_raw).strip() == "":
        raise RenderError("Zone serial missing counter")

    try:
        date_str = str(int(str(date_raw).strip()))
    except ValueError as exc:
        raise RenderError(f"Zone serial date is invalid: {date_raw}") from exc
    try:
        counter_int = int(str(counter_raw).strip())
    except ValueError as exc:
        raise RenderError(f"Zone serial counter is invalid: {counter_raw}") from exc

    serial = f"{date_str}{counter_int:02d}"

    context = {
        "zone": {
            "name": zone.get("name"),
            "serial": serial,
            "records": records,
        },
    }

    try:
        rendered = template.render(**context)
        return str(rendered)
    except (TemplateError, UndefinedError) as e:
        raise RenderError(f"Failed to render template {template_path}: {e}")
