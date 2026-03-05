"""DNS zone serial validation helpers."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from abhaile.dns.records import collect_zone_records
from abhaile.utils.errors import RenderError

GitShowCallable = Callable[..., subprocess.CompletedProcess[str]]


def _read_head_network_yaml(
    git_show: GitShowCallable = subprocess.run,
    cwd: Path | None = None,
) -> dict[str, Any] | None:
    """Read config/network.yaml from git HEAD.

    Args:
        git_show: Callable that performs the git command (for test injection).
        cwd: Working directory override.

    Returns:
        Parsed network dict, or None if unavailable.
    """
    try:
        result = git_show(
            ["git", "show", "HEAD:config/network.yaml"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path.cwd() if cwd is None else cwd,
        )
    except subprocess.CalledProcessError:
        return None
    except (OSError, PermissionError):
        return None

    try:
        head_network = yaml.safe_load(result.stdout)
    except yaml.YAMLError:
        return None

    return head_network if isinstance(head_network, dict) else None


def _get_git_head_serial(
    zone_name: str,
    git_show: GitShowCallable = subprocess.run,
    cwd: Path | None = None,
) -> dict[str, Any] | None:
    """Get zone serial from last git commit (HEAD).

    Args:
        zone_name: Name of the zone to look up.

    Returns:
        Dict with date, counter, content_hash from HEAD, or None if not found.
    """
    head_network = _read_head_network_yaml(git_show=git_show, cwd=cwd)
    if not head_network:
        return None

    dns_block = head_network.get("dns")
    if not isinstance(dns_block, dict):
        return None

    zones = dns_block.get("zones")
    if not isinstance(zones, list):
        return None

    for zone in zones:
        if not isinstance(zone, dict):
            continue
        if zone.get("name") == zone_name:
            serial = zone.get("serial", {})
            return serial if isinstance(serial, dict) else None

    return None


def validate_zone_serial(
    zone: dict[str, Any],
    network: dict[str, Any],
    deployed_services: list[str],
) -> None:
    """Validate a single zone serial, fails fast on first mismatch.

    Args:
        zone: Zone dict to validate.
        network: Network configuration (for record content hash).
        deployed_services: Services from mapping.yaml in mapping order.

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

    # Get current serial values from workspace
    current_date_str, current_date, current_counter = _parse_serial_fields(serial_info, zone_name)

    # Build zone content for hashing with current serial
    records = collect_zone_records(zone, network, deployed_services)
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
    computed_hash = compute_content_hash(zone_content)

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
    expected_hash = compute_content_hash(expected_content)

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


def validate_zone_serial_collect(
    zones: list[dict[str, Any]],
    network: dict[str, Any],
    deployed_services: list[str],
) -> list[str]:
    """Validate all zone serials, collecting all errors.

    Args:
        zones: List of zone dicts to validate.
        network: Network configuration (for record content hash).
        deployed_services: Services from mapping.yaml in mapping order.

    Returns:
        List of error messages (empty if all zones are valid).
    """
    errors = []

    for zone in zones:
        if zone.get("provider", {}).get("type") != "internal":
            continue  # Skip external zones

        try:
            validate_zone_serial(zone, network, deployed_services)
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
