"""DNS context building for CoreDNS zone files."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from .dns_serial import (
    calculate_serial,
    validate_serial_metadata,
)
from tools.common.core import strip_cidr, RenderError
from tools.common.dns import DesecProvider
from .dns_records import resolve_placeholder
from tools.common.core import resolve_placeholders


def _add_record(
    zones: dict[str, dict[str, Any]],
    zone_name: str,
    record: dict[str, Any],
) -> None:
    """Add a record to a zone and optionally create PTR entries.

    Args:
        zones: Zone map keyed by zone name.
        zone_name: Zone name to add the record into.
        record: Record dictionary with keys ``type``, ``name``, ``rdata``, and optional ``ptr``/``ptr_target``.
    """
    zones.setdefault(zone_name, {"records": []})
    zones[zone_name]["records"].append(record)

    # Generate PTR records when requested
    if record.get("ptr") and record.get("type", "").upper() == "A":
        ip = strip_cidr(record.get("rdata", ""))
        if not ip:
            return
        parts = ip.split(".")
        if len(parts) != 4:
            return

        reverse_zone = ".".join(reversed(parts[:3])) + ".in-addr.arpa."
        octet = parts[3]

        target = (
            record.get("ptr_target") or f"{record.get('name')}.{zone_name.rstrip('.')}"
        )
        if not target.endswith("."):
            target = f"{target}."

        zones.setdefault(reverse_zone, {"records": []})
        zones[reverse_zone]["records"].append(
            {
                "type": "PTR",
                "name": octet,
                "rdata": target,
            }
        )


def build_dns_context(
    deployed_services: list[str],
    network: dict[str, Any],
    hosts: dict[str, Any],
    services_meta: dict[str, Any],
    repo_root: Path,
    today: str | None = None,
) -> dict[str, Any]:
    """Build DNS context for CoreDNS zone file templates.

    Creates zone records from:
    - Services (A records for service addresses)
    - Hosts (A records from host interfaces with dns sections)
    - Static DNS records from network.yaml

    Serials are calculated by comparing zone record hashes against the last
    committed values in config/network.yaml. Counter increments only when
    records change.

    Args:
        deployed_services: List of service names to include
        network: Network configuration (current)
        hosts: Host configuration
        services_meta: Service metadata
        repo_root: Root directory of git repository (for reading committed config)
        today: Optional date string (YYYYMMDD) for testing; defaults to current date

    Returns:
        DNS context dict with zones, records, and per-zone serials

    Raises:
        RenderError: If zone is missing serial metadata in network.yaml
    """
    zones = {}

    # Build host DNS records first to maintain expected ordering
    for host_name, host_def in (hosts or {}).items():
        for dns_entry in host_def.get("dns", []) or []:
            zone_name = dns_entry.get("zone")
            if not zone_name:
                continue
            for record in dns_entry.get("records", []) or []:
                rdata = record.get("rdata", "")
                if rdata.startswith("%%") and rdata.endswith("%%"):
                    try:
                        rdata = resolve_placeholder(rdata, network)
                    except Exception as e:
                        raise RenderError(
                            f"Failed to resolve DNS placeholder '{rdata}' for host '{host_name}' "
                            f"in zone '{zone_name}': {e}"
                        ) from e
                record_dict = {
                    "type": record.get("type", "A").upper(),
                    "name": record.get("name"),
                    "rdata": rdata,
                    "ptr": record.get("ptr", False),
                }
                if record_dict["ptr"]:
                    record_dict["ptr_target"] = f"{host_name}.abhaile.home.arpa."
                _add_record(zones, zone_name, record_dict)

    # Then build service DNS records from network.yaml service definitions
    services = network.get("services", {})
    for svc_name in deployed_services:
        svc_def = services.get(svc_name)
        if not svc_def:
            continue
        for dns_entry in svc_def.get("dns", []) or []:
            zone_name = dns_entry.get("zone")
            if not zone_name:
                continue
            for rec in dns_entry.get("records", []) or []:
                rec_type = rec.get("type", "A").upper()
                rec_name = rec.get("name")
                rdata = rec.get("rdata", "")
                if "%%" in rdata:
                    try:
                        rdata = resolve_placeholders(rdata, network)
                    except RenderError as exc:
                        raise RenderError(
                            f"Failed to resolve DNS placeholder in rdata '{rdata}' "
                            f"for service '{svc_name}' in zone '{zone_name}': {exc}"
                        ) from exc
                record_dict = {
                    "type": rec_type,
                    "name": rec_name,
                    "rdata": rdata,
                    "ptr": rec.get("ptr", False),
                }
                _add_record(zones, zone_name, record_dict)

    # Convert zones dict to list of zone objects with calculated serials
    zones_list = []

    # Create mapping of zone names for validation
    zone_names = list(zones.keys())

    # Validate serial metadata exists for all zones
    validation_errors = validate_serial_metadata(zone_names, network)
    if validation_errors:
        raise RenderError(
            "DNS zone serial metadata validation failed:\n  "
            + "\n  ".join(validation_errors)
        )

    # Build zone list with serials calculated from committed config
    # Normalize zone names in map to not have trailing dots for consistent lookup
    dns_zones_map = {
        (z.get("name") or "").rstrip("."): z
        for z in network.get("dns", {}).get("zones", []) or []
    }

    pending_updates = []  # Track zones that need network.yaml updates

    for zone_name, zone_data in zones.items():
        # Get committed serial metadata for this zone (normalize for lookup)
        normalized_zone = zone_name.rstrip(".")
        zone_entry = dns_zones_map.get(normalized_zone, {})
        committed_serial = zone_entry.get("serial")
        provider = zone_entry.get("provider", "")

        # Skip serial calculation for desec.io zones (we don't control their serials)
        if provider == "desec.io":
            zones_list.append(
                {
                    "name": zone_name,
                    "records": zone_data.get("records", []),
                    "serial": "0000000000",  # Placeholder for desec.io zones
                    "content_hash": "",
                }
            )
            continue

        # Calculate new serial based on record hash
        records = zone_data.get("records", [])
        serial, new_hash, needs_update = calculate_serial(
            zone_name, records, committed_serial, today
        )

        if needs_update:
            pending_updates.append(
                {
                    "zone": zone_name,
                    "serial": {
                        "date": serial[:8],
                        "counter": serial[8:],
                        "content_hash": new_hash,
                    },
                }
            )

        zones_list.append(
            {
                "name": zone_name,
                "records": records,
                "serial": serial,
                "content_hash": new_hash,
            }
        )

    # If any zones need updates, raise error with clear instructions
    if pending_updates:
        error_lines = [
            "DNS zone records have changed. Update config/network.yaml with new serials:"
        ]
        for update in pending_updates:
            error_lines.append(f"\nZone: {update['zone']}")
            error_lines.append("  serial:")
            error_lines.append(f"    date: {update['serial']['date']}")
            error_lines.append(f"    counter: {update['serial']['counter']}")
            error_lines.append(f"    content_hash: {update['serial']['content_hash']}")
        raise RenderError("\n".join(error_lines))

    # Build providers mapping from network.dns.zones
    providers: dict[str, str] = {}
    for zone_def in network.get("dns", {}).get("zones", []) or []:
        zname = (zone_def.get("name") or "").rstrip(".")
        prov = zone_def.get("provider")
        if zname:
            providers[zname] = prov

    # Filter zones for coredns-common: include configured common zones + reverse zones
    zones_common = []
    for z in zones_list:
        zname = (z.get("name") or "").rstrip(".")
        if not zname:
            continue
        if zname.endswith(".in-addr.arpa") or providers.get(zname) == "coredns-common":
            zones_common.append(z)

    # Sort zones_common for consistent Corefile order:
    # 1. abhaile.home.arpa. (with trailing dot)
    # 2. svc.abhaile.home.arpa (without trailing dot)
    # 3. Reverse zones (in-addr.arpa), in ascending numeric order
    def zone_sort_key(zone):
        name = zone.get("name", "").rstrip(".")  # Remove trailing dot for comparison
        if name == "abhaile.home.arpa":
            return (0, zone.get("name", ""))
        elif name == "svc.abhaile.home.arpa":
            return (1, zone.get("name", ""))
        elif name.endswith(".in-addr.arpa"):
            # Extract VLAN ID for proper sorting: "20.20.172.in-addr.arpa" -> (2, 20)
            # Reverse zones are: <vlan_id>.<second_octet>.<third_octet>.in-addr.arpa
            # We want to sort by VLAN ID (first part)
            parts = name.split(".")
            if len(parts) >= 4:
                try:
                    # First part is the VLAN ID (e.g., "20" in "20.20.172.in-addr.arpa")
                    vlan_id = int(parts[0])
                    return (2, vlan_id, zone.get("name", ""))
                except ValueError:
                    return (2, 999, zone.get("name", ""))
            return (2, 999, zone.get("name", ""))
        else:
            return (3, zone.get("name", ""))

    zones_common.sort(key=zone_sort_key)

    return {
        "zones": zones_list,
        "zones_common": zones_common,
        "providers": providers,
    }


def build_desec_context(
    deployed_services: list[str],
    network: dict[str, Any],
) -> dict[str, Any]:
    """Build deSEC DNS context for public DNS records.

    Extracts DNS records for zones managed by deSEC based on network.dns.zones configuration.
    Only includes services with explicit DNS entries in deSEC-managed zones.

    Args:
        deployed_services: List of deployed service names
        network: Network configuration

    Returns:
        Context dict with desired_records list
    """
    desired_records = []

    # Get list of deSEC-managed zones from network.dns.zones
    desec_zones = set()
    for zone_def in network.get("dns", {}).get("zones", []):
        if zone_def.get("provider") == "desec.io":
            desec_zones.add(zone_def.get("name"))

    if not desec_zones:
        return {"desired_records": []}

    # Extract records from services that have DNS entries in deSEC zones
    services = network.get("services", {})

    for svc_name in deployed_services:
        svc_def = services.get(svc_name)
        if not svc_def:
            # Service runs on host network or has no DNS entries; skip
            continue

        # Check if service has DNS entries in any deSEC-managed zone
        for dns_entry in svc_def.get("dns", []):
            zone = dns_entry.get("zone")
            if zone not in desec_zones:
                continue

            # Extract records for this zone
            for record in dns_entry.get("records", []):
                rec_type = record.get("type", "A").upper()
                rec_name = record.get("name", "@")
                rdata = record.get("rdata", "")

                # Resolve %%variable%% patterns in rdata
                if "%%" in rdata:
                    try:
                        rdata = resolve_placeholders(rdata, network)
                    except RenderError as exc:
                        raise RenderError(
                            f"Failed to resolve placeholder '{rdata}' for service '{svc_name}'"
                        ) from exc

                desired_records.append(
                    {
                        "name": rec_name,
                        "type": rec_type,
                        "content": [rdata],
                    }
                )

    return {"desired_records": desired_records}


def plan_desec_changes(
    desired: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> dict[str, Any]:
    """Plan deSEC DNS changes (create/update/delete).

    Uses DesecProvider from tools.common.dns to plan record changes
    without depending on internal deSEC implementation details.

    Args:
        desired: List of desired DNS records in format:
                 [{"name": str, "type": str, "content": list[str]}, ...]
        current: List of current DNS records from provider in same format

    Returns:
        Plan dict with keys: create, update, delete
        {
            "create": [((name, type), [content])],
            "update": [((name, type), [content])],
            "delete": [(name, type)]
        }
    """
    provider = DesecProvider(token="", zone="abhaile.dedyn.io")
    return provider.plan_changes(desired, current)
