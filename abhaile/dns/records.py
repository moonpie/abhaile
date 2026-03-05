"""Record collection and processing helpers for DNS rendering."""

from __future__ import annotations

from typing import Any

from abhaile.dns.placeholders import _resolve_placeholder_value
from abhaile.utils.errors import RenderError


def collect_zone_records(
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

    # Collect host records
    hosts = network.get("hosts", {})
    for host_name, host_data in hosts.items():
        host_dns_list = host_data.get("dns", [])
        for dns_entry in host_dns_list:
            if dns_entry.get("zone") == zone_name:
                for record in dns_entry.get("records", []):
                    _add_record_and_ptr(record, zone_name, network, records)

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
                    _add_record_and_ptr(record, zone_name, network, records)

    # If this is a reverse zone, collect PTR records from forward zones
    if zone_name and _is_reverse_zone(zone_name):
        _collect_ptr_records_for_reverse_zone(zone_name, network, deployed_services, records)

    return records


def _add_record_and_ptr(
    record: dict[str, Any],
    zone_name: str | None,
    network: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    """Add a record and generate PTR record if ptr: true."""
    resolved_record = dict(record)
    if "rdata" in resolved_record:
        resolved_record["rdata"] = _resolve_placeholder_value(resolved_record["rdata"], network)
    if "type" in resolved_record and isinstance(resolved_record["type"], str):
        resolved_record["type"] = resolved_record["type"].upper()
    records.append(resolved_record)

    # Generate PTR record if requested
    if record.get("ptr") and resolved_record.get("type") in ("A", "AAAA"):
        if zone_name and not _is_reverse_zone(zone_name):
            pass  # PTR records are collected in reverse zones


def _is_reverse_zone(zone_name: str | None) -> bool:
    """Return True if the zone name is an IPv4/IPv6 reverse zone."""
    if not zone_name:
        return False
    return zone_name.endswith(".in-addr.arpa.") or zone_name.endswith(".ip6.arpa.")


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

    if zone_name.endswith(".ip6.arpa."):
        raise RenderError(f"IPv6 PTR generation is not supported for reverse zone '{zone_name}'")

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
                    if _ip_belongs_to_reverse_zone(rdata, zone_name):
                        # Generate PTR record
                        ptr_name = _get_reverse_dns_name(rdata, zone_name)
                        ptr_fqdn = f"{record.get('name', '').rstrip('.')}.{zone.rstrip('.')}."
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
                    if _ip_belongs_to_reverse_zone(rdata, zone_name):
                        # Generate PTR record
                        ptr_name = _get_reverse_dns_name(rdata, zone_name)
                        ptr_fqdn = f"{record.get('name', '').rstrip('.')}.{zone.rstrip('.')}."
                        ptr_record = {
                            "name": ptr_name,
                            "type": "PTR",
                            "rdata": ptr_fqdn,
                            "ttl": record.get("ttl", 3600),
                        }
                        records.append(ptr_record)


def _ip_belongs_to_reverse_zone(ip: str, reverse_zone: str) -> bool:
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
    if len(reversed_parts) == 2:  # /16 network
        return parts[:2] == reversed_parts
    if len(reversed_parts) == 1:  # /8 network
        return parts[:1] == reversed_parts
    return False


def _get_reverse_dns_name(ip: str, reverse_zone: str) -> str:
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
    if len(rz_parts) == 2:  # /16 network
        return ".".join(parts[2:])
    if len(rz_parts) == 1:  # /8 network
        return ".".join(parts[1:])
    return parts[3]
