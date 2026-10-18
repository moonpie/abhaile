"""DNS zone serial validation helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from abhaile.dns.records import collect_zone_records
from abhaile.utils.errors import RenderError


def validate_zone_serial(
    zone: dict[str, Any],
    network: dict[str, Any],
    deployed_services: list[str],
    config_root: Path,
) -> None:
    """Validate a single zone serial, fails fast on first mismatch.

    Args:
        zone: Zone dict to validate.
        network: Network configuration (for record content hash).
        deployed_services: Services from mapping.yaml in mapping order.
        config_root: Config root path for resolving zone templates.

    Raises:
        RenderError: If serial is invalid (content hash mismatch).
    """
    zone_name = zone.get("name")
    if not zone_name:
        return

    serial_info = zone.get("serial", {})
    if not serial_info:
        raise RenderError(f"Zone '{zone_name}' missing serial configuration")

    # Get current hash from network.yaml
    current_hash = serial_info.get("content_hash")
    if not current_hash:
        raise RenderError(f"Zone '{zone_name}' missing content_hash in serial")

    _parse_serial_fields(serial_info, zone_name)

    zone_content = _render_zone_content_for_hash(zone, network, deployed_services, config_root)
    computed_hash = compute_content_hash(zone_content)

    # Check if content hash matches
    if computed_hash == current_hash:
        return  # All is well

    raise RenderError(
        f"Zone '{zone_name}' content hash mismatch.\n"
        "  Update the zone serial and set serial.content_hash for the declared serial to:\n"
        f"    serial.content_hash: {computed_hash}"
    )


def validate_zone_serial_collect(
    zones: list[dict[str, Any]],
    network: dict[str, Any],
    deployed_services: list[str],
    config_root: Path,
) -> list[str]:
    """Validate all zone serials, collecting all errors.

    Args:
        zones: List of zone dicts to validate.
        network: Network configuration (for record content hash).
        deployed_services: Services from mapping.yaml in mapping order.
        config_root: Config root path for resolving zone templates.

    Returns:
        List of error messages (empty if all zones are valid).
    """
    errors = []

    for zone in zones:
        if zone.get("provider", {}).get("type") != "internal":
            continue  # Skip external zones

        try:
            validate_zone_serial(zone, network, deployed_services, config_root=config_root)
        except RenderError as e:
            errors.append(str(e))

    return errors


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of zone file content.

    Args:
        content: Zone file content string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_serial_fields(
    serial_info: dict[str, Any],
    zone_name: str,
) -> tuple[str, int, int]:
    """Parse serial date and counter fields.

    Raises RenderError if values are missing or invalid.
    """
    date_raw = serial_info.get("date")
    if date_raw is None or str(date_raw).strip() == "":
        raise RenderError(f"Zone '{zone_name}' missing serial.date")

    counter_raw = serial_info.get("counter")
    if counter_raw is None or str(counter_raw).strip() == "":
        raise RenderError(f"Zone '{zone_name}' missing serial.counter")

    try:
        date_int = int(str(date_raw).strip())
    except ValueError as exc:
        raise RenderError(f"Zone '{zone_name}' invalid serial.date: {date_raw}") from exc

    try:
        counter_int = int(str(counter_raw).strip())
    except ValueError as exc:
        raise RenderError(f"Zone '{zone_name}' invalid serial.counter: {counter_raw}") from exc

    return str(date_int), date_int, counter_int


def _render_zone_content_for_hash(
    zone: dict[str, Any],
    network: dict[str, Any],
    deployed_services: list[str],
    config_root: Path,
) -> str:
    """Render canonical zone content for content-hash validation.

    Uses the same zone template resolution path as DNS rendering to ensure
    validation hashes match actual rendered output.

    Args:
        zone: Zone dict to render.
        network: Network configuration.
        deployed_services: Services from mapping.yaml in mapping order.
        config_root: Config root path for resolving zone templates.

    Returns:
        Rendered zone content string.
    """
    from abhaile.dns.renderer import get_zone_files_config, render_zone_template

    records = collect_zone_records(zone, network, deployed_services)
    zone_name = str(zone.get("name", ""))

    provider = zone.get("provider", {}) or {}
    provider_name = provider.get("name")
    if not provider_name:
        raise RenderError(f"Zone '{zone_name}' missing provider.name")

    zone_files = get_zone_files_config(str(provider_name), config_root)
    for zone_file_entry in zone_files:
        zone_pattern = str(zone_file_entry.get("zone", ""))
        if zone_pattern != "*" and zone_name != zone_pattern:
            continue

        file_config = zone_file_entry.get("file", {}) or {}
        source_config = file_config.get("source", {}) or {}
        template_path = source_config.get("template")
        if isinstance(template_path, str) and template_path:
            return render_zone_template(template_path, zone, records, config_root)

    raise RenderError(
        f"Zone '{zone_name}' provider '{provider_name}' has no matching zone_files template"
    )
