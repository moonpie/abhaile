"""DNS serial number management using commit-based tracking.

Serials are stored in config/network.yaml and based on content hashes of zone records.
When zone records change, the serial counter increments.
This ensures deterministic serials across hosts and prevents unnecessary increments.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def get_committed_network_config(repo_root: Path) -> dict[str, Any] | None:
    """Get the last committed version of config/network.yaml.

    Args:
        repo_root: Root directory of the git repository

    Returns:
        Parsed network.yaml from HEAD, or None if not found/not in git

    Raises:
        Exception: If git command fails unexpectedly
    """
    try:
        result = subprocess.run(
            ["git", "show", "HEAD:config/network.yaml"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return yaml.safe_load(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # Git not available, not in repo, or file doesn't exist in HEAD
        pass
    return None


def calculate_record_hash(records: list[dict[str, Any]]) -> str:
    """Calculate deterministic hash of zone records (not including serial).

    Sorts records by name and type to ensure consistent hashing.

    Args:
        records: List of DNS records with type, name, rdata, ptr fields

    Returns:
        Hex digest of the records hash (SHA256)
    """
    # Create canonical form: sort records, exclude any serial data
    canonical = []
    for rec in records:
        rec_dict = {
            "type": rec.get("type", "").upper(),
            "name": rec.get("name", ""),
            "rdata": rec.get("rdata", ""),
            "ptr": rec.get("ptr", False),
        }
        canonical.append(rec_dict)

    # Sort for determinism
    canonical.sort(key=lambda r: (r["name"], r["type"], r["rdata"]))

    # Hash the canonical representation
    canonical_str = str(canonical)
    return hashlib.sha256(canonical_str.encode()).hexdigest()


def calculate_serial(
    zone_name: str,
    zone_records: list[dict[str, Any]],
    committed_serial: dict[str, Any] | None,
    today: str | None = None,
) -> tuple[str, str, bool]:
    """Calculate DNS serial and update hash based on record changes.

    Serial format is YYYYMMDDNN where:
    - YYYYMMDD is today's date
    - NN is a counter (00-99) that increments when records change

    IMPORTANT: When records change, this returns the NEXT serial but does NOT
    update network.yaml. User must manually update network.yaml with the returned
    serial values to commit the change.

    Args:
        zone_name: Name of the DNS zone
        zone_records: List of records in this zone
        committed_serial: Last committed serial metadata from network.yaml
                         Expected: {"date": "YYYYMMDD", "counter": NN, "content_hash": "..."}

    Returns:
        Tuple of (serial_string, new_content_hash, needs_update)
        needs_update: True if zone content changed and network.yaml needs updating
        Example: ("2026010503", "abc123def456...", True)
    """
    # Allow tests to inject a deterministic date; default to today's date
    today = today or datetime.now().strftime("%Y%m%d")
    new_hash = calculate_record_hash(zone_records)

    # If no committed serial (new zone), start at 00
    if not committed_serial:
        return (today + "00", new_hash, False)

    committed_hash = committed_serial.get("content_hash", "")
    committed_date = committed_serial.get("date", "")
    committed_counter = committed_serial.get("counter", 0)

    # If content hasn't changed, reuse the serial
    if new_hash == committed_hash:
        # Reuse committed counter, but update date if it changed day
        if today == committed_date:
            # Same day, same content → same serial
            return (today + f"{committed_counter:02d}", new_hash, False)
        else:
            # New day, but same content → keep counter (don't reset)
            # This preserves serial sequence across day boundaries for unchanged zones
            return (today + f"{committed_counter:02d}", new_hash, False)

    # Content changed → increment counter
    if today == committed_date:
        # Same day → increment counter
        new_counter = min(committed_counter + 1, 99)  # Cap at 99
    else:
        # New day → reset to 00
        new_counter = 0

    return (today + f"{new_counter:02d}", new_hash, True)


def validate_serial_metadata(
    zone_names: list[str],
    network_config: dict[str, Any],
) -> list[str]:
    """Validate that all zones have serial metadata in network.yaml.

    Skips zones with provider 'desec.io' since we don't control their serials.

    Args:
        zone_names: List of zone names that will be rendered
        network_config: The network.yaml config

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    # Normalize all zone names in network.yaml to not have trailing dots for comparison
    dns_zones = {
        (z.get("name") or "").rstrip("."): z
        for z in network_config.get("dns", {}).get("zones", [])
    }

    for zone_name in zone_names:
        # Normalize the zone name to not have trailing dot for comparison
        normalized_name = zone_name.rstrip(".")
        if normalized_name not in dns_zones:
            errors.append(
                f"Zone '{zone_name}' missing from dns.zones in network.yaml. "
                f"Add an entry with serial metadata: "
                f"{{name: {zone_name}, provider: coredns-common, serial: {{date: YYYYMMDD, counter: 0, content_hash: ''}}}}"
            )
        else:
            zone_entry = dns_zones[normalized_name]
            provider = zone_entry.get("provider", "")

            # Skip serial validation for desec.io zones (we don't control their serials)
            if provider == "desec.io":
                continue

            if "serial" not in zone_entry:
                errors.append(
                    f"Zone '{zone_name}' missing 'serial' metadata in network.yaml. "
                    f"Add: serial: {{date: 20260105, counter: 0, content_hash: ''}}"
                )
            else:
                serial = zone_entry.get("serial", {})
                if (
                    "date" not in serial
                    or "counter" not in serial
                    or "content_hash" not in serial
                ):
                    errors.append(
                        f"Zone '{zone_name}' serial metadata incomplete. "
                        f"Must have: date (YYYYMMDD), counter (0-99), content_hash (string)"
                    )

    return errors
