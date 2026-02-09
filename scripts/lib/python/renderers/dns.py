"""Render DNS zone files from network configuration."""

from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from utils.config import read_yaml
from utils.errors import RenderError


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
    provider_to_services: dict[str, list[str]] = {}

    def resolve_service_composition(service_name: str) -> dict[str, Any]:
        """Resolve full composition for a service including inherited configs."""
        service_path = config_root / "services" / service_name / "service.yaml"
        if not service_path.exists():
            return {}

        service_data = read_yaml(service_path) or {}
        composition = service_data.get("composition", {}) or {}

        # Merge included compositions
        includes = composition.get("include", []) or []
        merged = {}
        for included_service in includes:
            included_comp = resolve_service_composition(included_service)
            # Deep merge - nested dicts are merged, not replaced
            for key, value in included_comp.items():
                if (
                    key in merged
                    and isinstance(merged[key], dict)
                    and isinstance(value, dict)
                ):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value

        # Apply service's own composition (overrides includes)
        for key, value in composition.items():
            if key == "include":
                continue  # Skip include directive itself
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value

        return merged

    # Build map of provider.name -> services on THIS HOST that provide zones
    # Only scan services running on the current host
    for service_name in host_services:
        service_path = config_root / "services" / service_name / "service.yaml"
        if not service_path.exists():
            continue

        # Resolve full composition including inherited configs
        composition = resolve_service_composition(service_name)

        # Check if service has dns.zone_files (inherited or direct)
        dns_config = composition.get("dns", {})
        zone_files = dns_config.get("zone_files", [])

        if not zone_files:
            continue

        # Read service definition to get includes
        service_def = read_yaml(service_path) or {}

        # Determine which provider this service provides zones for
        # Services typically inherit zone_files from base services (like coredns-common)
        # We match based on the base service name in the include chain
        includes = service_def.get("composition", {}).get("include", [])
        for include in includes:
            if include not in provider_to_services:
                provider_to_services[include] = []
            if service_name not in provider_to_services[include]:
                provider_to_services[include].append(service_name)

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
        records = _collect_zone_records(zone, network, all_services)

        # Get zone_files configuration from provider service
        zone_files = _get_zone_files_config(provider_name, host_services, config_root)
        if not zone_files:
            raise RenderError(
                f"Zone '{zone_name}' provider '{provider_name}' has no zone_files config"
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
            zone_content = _render_zone_template(
                template_path, zone, records, config_root
            )

            # Find services that provide this zone (based on provider.name)
            providing_services = provider_to_services.get(provider_name, [])

            if not providing_services:
                raise RenderError(
                    f"Zone '{zone_name}' has provider '{provider_name}' but no services "
                    f"in mapping.yaml provide zones for that provider. "
                    f"Check that services include '{provider_name}' and have dns.zone_files."
                )

            # Render zone file to each providing service
            for service_name in providing_services:
                # Replace zone.zone placeholder in destination with actual zone name
                zone_name_stripped = zone_name.rstrip(".")
                # Remove leading / from destination if present (should be relative)
                actual_dest = dest_path.lstrip("/")
                # Replace zone.zone placeholder with actual zone name
                actual_dest = actual_dest.replace(
                    "zone.zone", f"{zone_name_stripped}.zone"
                )

                zone_output_dir = (
                    output_dir / "services" / service_name / Path(actual_dest).parent
                )
                zone_output_dir.mkdir(parents=True, exist_ok=True)

                # Write zone file
                zone_file = zone_output_dir / Path(actual_dest).name
                zone_file.write_text(zone_content, encoding="utf-8")


def _get_zone_files_config(
    provider_name: str,
    host_services: list[str],
    config_root: Path,
) -> list[dict[str, Any]]:
    """Get zone_files configuration from a provider service.

    Args:
        provider_name: Name of the provider service (e.g., coredns-common).
        host_services: Services on the current host.
        config_root: Config root directory.

    Returns:
        List of zone_files entries, or empty list if provider not found on this host.
    """
    # Find a service on this host that includes the provider
    for service_name in host_services:
        service_path = config_root / "services" / service_name / "service.yaml"
        if not service_path.exists():
            continue

        service_data = read_yaml(service_path) or {}
        composition = service_data.get("composition", {}) or {}

        # Check if this service includes the provider
        includes = composition.get("include", []) or []
        if provider_name in includes:
            # Read the provider service to get zone_files config
            provider_path = config_root / "services" / provider_name / "service.yaml"
            if provider_path.exists():
                provider_data = read_yaml(provider_path) or {}
                provider_comp = provider_data.get("composition", {}) or {}
                dns_config = provider_comp.get("dns", {})
                return dns_config.get("zone_files", [])

    return []


def _render_zone_template(
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
    env = Environment(
        loader=FileSystemLoader(str(service_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    try:
        template = env.get_template(rel_path)
    except Exception as e:
        raise RenderError(f"Failed to load template {template_path}: {e}")

    # Prepare context for template
    serial_info = zone.get("serial", {})
    serial = str(serial_info.get("date", "20260101")).strip() + str(
        serial_info.get("counter", "00")
    ).zfill(2)

    context = {
        "zone": {
            "name": zone.get("name"),
            "serial": serial,
            "records": records,
        },
    }

    try:
        return template.render(**context)
    except Exception as e:
        raise RenderError(f"Failed to render template {template_path}: {e}")


def _get_git_head_serial(zone_name: str) -> dict[str, Any] | None:
    """Get zone serial from last git commit (HEAD).

    Args:
        zone_name: Name of the zone to look up.

    Returns:
        Dict with date, counter, content_hash from HEAD, or None if not found.
    """
    try:
        # Get network.yaml from git HEAD
        result = subprocess.run(
            ["git", "show", "HEAD:config/network.yaml"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path.cwd(),
        )
        head_network = yaml.safe_load(result.stdout)
    except subprocess.CalledProcessError:
        # Git command failed (e.g., no HEAD, working directory issue)
        return None
    except Exception:
        # YAML parsing or other unexpected error
        return None

    if (
        not head_network
        or "dns" not in head_network
        or "zones" not in head_network["dns"]
    ):
        return None

    zones = head_network["dns"]["zones"]
    for zone in zones:
        if zone.get("name") == zone_name:
            return zone.get("serial", {})

    return None


def _validate_zone_serial(zone: dict[str, Any], network: dict[str, Any]) -> None:
    """Validate a single zone serial, fails fast on first mismatch.

    Args:
        zone: Zone dict to validate.
        network: Network configuration (for record content hash).

    Raises:
        RenderError: If serial is invalid (content hash mismatch).
    """
    zone_name = zone.get("name")
    if not zone_name:
        return

    serial_info = zone.get("serial", {})
    if not serial_info:
        return

    # Get current hash from network.yaml
    current_hash = serial_info.get("content_hash")
    if not current_hash:
        raise RenderError(f"Zone '{zone_name}' missing content_hash in serial")

    # Get current serial values from workspace
    current_date_raw = serial_info.get("date", "")
    try:
        current_date = int(str(current_date_raw).strip())
        current_date_str = str(current_date)
    except ValueError:
        current_date_str = "20260101"
        current_date = int(current_date_str)

    try:
        current_counter = int(str(serial_info.get("counter", "0")).strip())
    except ValueError:
        current_counter = 0

    # Build zone content for hashing with current serial
    records = _collect_zone_records(zone, network, [])
    zone_name_stripped = zone_name.rstrip(".")
    serial_str = f"{current_date_str}{current_counter:02d}"

    lines = []
    lines.append(f"$ORIGIN {zone_name}")
    lines.append("")
    lines.append(
        f"{zone_name_stripped}. 3600 IN SOA ns1.{zone_name_stripped}. "
        f"hostmaster.{zone_name_stripped}. {serial_str} 3600 1800 604800 86400"
    )
    lines.append(f"{zone_name_stripped}. 3600 IN NS ns1.{zone_name_stripped}.")
    lines.append("")

    for record in records:
        record_name = record.get("name", "").rstrip(".")
        record_type = record.get("type", "").upper()
        rdata = record.get("rdata", "").strip()
        ttl = record.get("ttl", 3600)

        if not record_type or not rdata:
            continue

        lines.append(f"{record_name} {ttl} IN {record_type} {rdata}")

    lines.append("")
    zone_content = "\n".join(lines)
    computed_hash = _compute_content_hash(zone_content)

    # Check if content hash matches
    if computed_hash == current_hash:
        return  # All is well

    # Hash mismatch - compute expected serial and hash
    # Get last serial from git HEAD for comparison
    head_serial = _get_git_head_serial(zone_name)

    today_str = datetime.now().strftime("%Y%m%d")
    today_int = int(today_str)

    if head_serial:
        head_date_raw = head_serial.get("date", "")
        try:
            head_date = int(str(head_date_raw).strip())
        except ValueError:
            head_date = today_int

        try:
            head_counter = int(str(head_serial.get("counter", "0")).strip())
        except ValueError:
            head_counter = 0
    else:
        head_date = today_int
        head_counter = 0

    # Compute expected serial based on git HEAD vs today
    if head_date == today_int:
        expected_date_str = today_str
        expected_counter = head_counter + 1
    else:
        expected_date_str = today_str
        expected_counter = 0

    expected_serial_str = f"{expected_date_str}{expected_counter:02d}"

    # Compute expected hash with expected serial
    expected_lines = list(lines)
    expected_lines[2] = (
        f"{zone_name_stripped}. 3600 IN SOA ns1.{zone_name_stripped}. "
        f"hostmaster.{zone_name_stripped}. {expected_serial_str} 3600 1800 604800 86400"
    )
    expected_content = "\n".join(expected_lines)
    expected_hash = _compute_content_hash(expected_content)

    # Compare expected vs current workspace values and collect differences
    mismatches = []

    if int(expected_date_str) != current_date:
        mismatches.append(f"    serial.date: {expected_date_str}")

    if expected_counter != current_counter:
        mismatches.append(f"    serial.counter: {expected_counter:02d}")

    if expected_hash != current_hash:
        mismatches.append(f"    serial.content_hash: {expected_hash}")

    if mismatches:
        error_lines = [
            f"Zone '{zone_name}' content hash mismatch.",
            "  To fix: update zone.serial in config/network.yaml",
        ]
        error_lines.extend(mismatches)
        raise RenderError("\n".join(error_lines))


def _validate_zone_serial_collect(
    zones: list[dict[str, Any]],
    network: dict[str, Any],
) -> list[str]:
    """Validate all zone serials, collecting all errors.

    Args:
        zones: List of zone dicts to validate.
        network: Network configuration (for record content hash).

    Returns:
        List of error messages (empty if all zones are valid).
    """
    errors = []

    for zone in zones:
        if zone.get("provider", {}).get("type") != "internal":
            continue  # Skip external zones

        try:
            _validate_zone_serial(zone, network)
        except RenderError as e:
            errors.append(str(e))

    return errors


_PLACEHOLDER_PATTERN = re.compile(r"%%(.*)%%")


def _resolve_placeholder_value(value: Any, network: dict[str, Any]) -> Any:
    """Resolve placeholder values in strings.

    Handles expressions like '%%network.services.vault.address | strip_cidr%%'.

    Args:
        value: Value to resolve (string with placeholders or other type).
        network: Network configuration dict.

    Returns:
        Resolved value.
    """
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


def _lookup_network_value(path_expr: str, network: dict[str, Any]) -> Any:
    """Look up a value in the network dict using dot notation.

    Handles keys that contain dots (e.g., interface names like 'enp0s31f6.100')
    by trying progressively longer key combinations.

    Args:
        path_expr: Dot-separated path starting with 'network.' (e.g., 'network.services.vault.address').
        network: Network configuration dict.

    Returns:
        Value at the specified path.

    Raises:
        RenderError: If path not found or doesn't start with 'network.'.
    """
    if not path_expr.startswith("network."):
        raise RenderError(f"Unsupported placeholder root: {path_expr}")

    parts = path_expr.split(".")[1:]  # Remove 'network' prefix
    current: Any = network

    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            raise RenderError(f"Placeholder path not found: {path_expr}")

        # Try progressively longer keys (e.g., for 'enp0s31f6.100.address',
        # try 'enp0s31f6.100', then 'enp0s31f6')
        found = False
        for length in range(len(parts) - i, 0, -1):
            candidate_key = ".".join(parts[i : i + length])
            if candidate_key in current:
                current = current[candidate_key]
                i += length
                found = True
                break

        if not found:
            raise RenderError(f"Placeholder path not found: {path_expr}")

    return current


def _strip_cidr(address: str) -> str:
    """Strip CIDR suffix from IP address.

    Args:
        address: IP address with optional CIDR (e.g., '192.168.1.1/24').

    Returns:
        IP address without CIDR suffix.
    """
    if "/" not in address:
        return address
    return address.split("/", 1)[0]


def _ip_to_reverse_dns(ip_address: str) -> str:
    """Convert IPv4 address to reverse DNS notation.

    Args:
        ip_address: IPv4 address (e.g., '192.168.1.10').

    Returns:
        Reverse DNS notation (e.g., '10.1.168.192.in-addr.arpa.').
    """
    parts = ip_address.split(".")
    if len(parts) != 4:
        raise RenderError(f"Invalid IPv4 address: {ip_address}")
    return ".".join(reversed(parts)) + ".in-addr.arpa."


def _collect_zone_records(
    zone: dict[str, Any],
    network: dict[str, Any],
    deployed_services: list[str],
) -> list[dict[str, Any]]:
    """Collect DNS records for a zone from hosts and deployed services.

    Records are ordered:
    1. Host records in network.yaml definition order
    2. Service records in network.yaml definition order (only from deployed services)
    Within each host/service, records preserve definition order.

    For A/AAAA records marked with ptr: true, corresponding PTR records are
    automatically generated for the appropriate reverse zone.

    Placeholder values in rdata fields (e.g., '%%network.services.vault.address | strip_cidr%%')
    are resolved to actual values.

    Args:
        zone: Zone configuration dict.
        network: Network configuration dict.
        deployed_services: List of services deployed (from mapping.yaml) - only these service records are included.

    Returns:
        List of record dicts (name, type, rdata, ttl) with placeholders resolved.
    """
    zone_name = zone.get("name")
    records: list[dict[str, Any]] = []

    # Helper to add records and generate PTR records if needed
    def add_record_and_ptr(record: dict[str, Any], source_name: str) -> None:
        """Add a record and generate PTR record if ptr: true."""
        # Resolve placeholders in rdata field
        resolved_record = dict(record)
        if "rdata" in resolved_record:
            resolved_record["rdata"] = _resolve_placeholder_value(
                resolved_record["rdata"], network
            )
        if "type" in resolved_record and isinstance(resolved_record["type"], str):
            resolved_record["type"] = resolved_record["type"].upper()
        records.append(resolved_record)

        # Generate PTR record if requested
        if record.get("ptr") and resolved_record["type"] in ("A", "AAAA"):
            # Only generate PTR for forward zones (not reverse zones)
            if not zone_name.endswith(".in-addr.arpa.") and not zone_name.endswith(
                ".ip6.arpa."
            ):
                pass  # PTR records are collected in reverse zones

    # Collect host records
    hosts = network.get("hosts", {})
    for host_name, host_data in hosts.items():
        host_dns_list = host_data.get("dns", [])
        for dns_entry in host_dns_list:
            if dns_entry.get("zone") == zone_name:
                for record in dns_entry.get("records", []):
                    add_record_and_ptr(record, host_name)

    # Collect service records (only from deployed services, in mapping.yaml order)
    services = network.get("services", {})
    for service_name in deployed_services:  # Iterate in mapping.yaml order
        if service_name not in services:  # Check if service exists in network.yaml
            continue
        service_data = services[service_name]
        service_dns_list = service_data.get("dns", [])
        for dns_entry in service_dns_list:
            if dns_entry.get("zone") == zone_name:
                for record in dns_entry.get("records", []):
                    add_record_and_ptr(record, service_name)

    # If this is a reverse zone, collect PTR records from forward zones
    if zone_name.endswith(".in-addr.arpa.") or zone_name.endswith(".ip6.arpa."):
        _collect_ptr_records_for_reverse_zone(
            zone_name, network, deployed_services, records
        )

    return records


def _collect_ptr_records_for_reverse_zone(
    zone_name: str,
    network: dict[str, Any],
    deployed_services: list[str],
    records: list[dict[str, Any]],
) -> None:
    """Collect PTR records for a reverse zone from forward zones.

    Scans all forward zones looking for A/AAAA records with ptr: true that
    belong to this reverse zone, and adds corresponding PTR records.

    Args:
        zone_name: Reverse zone name (e.g., '20.20.172.in-addr.arpa.').
        network: Network configuration dict.
        deployed_services: List of deployed services.
        records: List to append PTR records to (modified in-place).
    """

    # Helper to check if an IP belongs to this reverse zone
    def ip_belongs_to_reverse_zone(ip: str, reverse_zone: str) -> bool:
        """Check if IP address belongs to the specified reverse zone.

        For 172.20.20.10 and reverse zone 20.20.172.in-addr.arpa., returns True.
        For 172.20.100.10 and reverse zone 20.20.172.in-addr.arpa., returns False.
        """
        # Remove trailing dot if present
        rz = reverse_zone.rstrip(".")
        parts = ip.split(".")

        # Extract the octets from the reverse zone name
        # e.g., "20.20.172.in-addr.arpa" -> ["20", "20", "172"]
        rz_parts = rz.replace(".in-addr.arpa", "").split(".")

        # Reverse the reversed octets to get original IP octets
        # e.g., ["20", "20", "172"] -> ["172", "20", "20"]
        reversed_parts = list(reversed(rz_parts))

        # Check if the IP starts with these octets
        if len(reversed_parts) == 3:  # /24 network
            return parts[:3] == reversed_parts
        elif len(reversed_parts) == 2:  # /16 network
            return parts[:2] == reversed_parts
        elif len(reversed_parts) == 1:  # /8 network
            return parts[:1] == reversed_parts
        else:
            return False

    # Helper to get reverse DNS name for an IP
    def get_reverse_dns_name(ip: str, reverse_zone: str) -> str:
        """Get the PTR record name (final octets) for an IP in the reverse zone.

        For 172.20.20.10 in 20.20.172.in-addr.arpa., the name is "10".
        For 172.20.100.10 in 100.20.172.in-addr.arpa., the name is "10".
        """
        # Remove trailing dot if present
        rz = reverse_zone.rstrip(".")
        parts = ip.split(".")

        # Extract the octets from the reverse zone name
        rz_parts = rz.replace(".in-addr.arpa", "").split(".")

        # The PTR record name is the remaining octets after the zone octets
        # For /24 zone, use the last octet of the IP
        if len(rz_parts) == 3:  # /24 network
            return parts[3]
        elif len(rz_parts) == 2:  # /16 network
            return ".".join(parts[2:])
        elif len(rz_parts) == 1:  # /8 network
            return ".".join(parts[1:])
        else:
            return parts[3]  # Fallback to last octet

    # Scan all forward zones for PTR records
    hosts = network.get("hosts", {})
    for host_name, host_data in hosts.items():
        host_dns_list = host_data.get("dns", [])
        for dns_entry in host_dns_list:
            zone = dns_entry.get("zone")
            for record in dns_entry.get("records", []):
                if record.get("ptr") and record.get("type", "").lower() == "a":
                    # Resolve the IP address
                    rdata = _resolve_placeholder_value(record.get("rdata", ""), network)
                    if ip_belongs_to_reverse_zone(rdata, zone_name):
                        # Generate PTR record
                        ptr_name = get_reverse_dns_name(rdata, zone_name)
                        ptr_fqdn = (
                            f"{record.get('name', '').rstrip('.')}.{zone.rstrip('.')}."
                        )
                        ptr_record = {
                            "name": ptr_name,
                            "type": "PTR",
                            "rdata": ptr_fqdn,
                            "ttl": record.get("ttl", 3600),
                        }
                        records.append(ptr_record)

    # Scan services for PTR records
    services = network.get("services", {})
    for service_name in deployed_services:
        if service_name not in services:
            continue
        service_data = services[service_name]
        service_dns_list = service_data.get("dns", [])
        for dns_entry in service_dns_list:
            zone = dns_entry.get("zone")
            for record in dns_entry.get("records", []):
                if record.get("ptr") and record.get("type", "").lower() == "a":
                    # Resolve the IP address
                    rdata = _resolve_placeholder_value(record.get("rdata", ""), network)
                    if ip_belongs_to_reverse_zone(rdata, zone_name):
                        # Generate PTR record
                        ptr_name = get_reverse_dns_name(rdata, zone_name)
                        ptr_fqdn = (
                            f"{record.get('name', '').rstrip('.')}.{zone.rstrip('.')}."
                        )
                        ptr_record = {
                            "name": ptr_name,
                            "type": "PTR",
                            "rdata": ptr_fqdn,
                            "ttl": record.get("ttl", 3600),
                        }
                        records.append(ptr_record)


def _compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of zone file content.

    Args:
        content: Zone file content string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
