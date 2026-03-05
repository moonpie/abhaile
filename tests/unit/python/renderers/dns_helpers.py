"""Helper utilities for DNS renderer tests."""

from typing import Any, Dict, List


def build_zone_content_for_hash(zone: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    """Build zone content used for hashing in serial validation tests."""
    zone_name = zone.get("name", "")
    zone_name_stripped = zone_name.rstrip(".")
    serial_info = zone.get("serial", {})
    if not isinstance(serial_info, dict) or not serial_info:
        raise ValueError("Zone serial configuration is required")
    if serial_info.get("date") is None or str(serial_info.get("date")).strip() == "":
        raise ValueError("Zone serial.date is required")
    if serial_info.get("counter") is None or str(serial_info.get("counter")).strip() == "":
        raise ValueError("Zone serial.counter is required")

    serial_str = str(int(str(serial_info.get("date")).strip())) + str(
        int(str(serial_info.get("counter")).strip())
    ).zfill(2)

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
    return "\n".join(lines)
