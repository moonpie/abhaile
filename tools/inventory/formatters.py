"""Inventory formatters - convert structured data to markdown output.

Formatters take analyzed inventory data and produce markdown documents.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from tools.common.core import get_logger, strip_cidr


logger = get_logger(__name__)


def _escape_asterisks(text: str) -> str:
    """Escape literal asterisks in specific contexts (glob patterns, wildcard domains).

    Only escapes asterisks in clearly problematic contexts, preserving all markdown.
    """
    # Simple targeted approach: only escape asterisks in these specific patterns:
    # 1. Glob patterns: config/services/*/...
    # 2. Wildcard domains: *.example.com

    # Replace config/services/* -> config/services\/*
    text = text.replace("config/services/*/", "config/services/\\*/")

    # Replace *.something (wildcard domain) -> \*.something
    # But only if followed by a dot (domain pattern)

    text = re.sub(
        r"(\s|^)\*\.([a-z0-9\-]+\.[a-z0-9\-\.]+)",
        r"\1\\*.\2",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _clean_markdown(content: str) -> str:
    """Remove double blank lines from markdown, keeping only single blank lines.

    Also escapes literal asterisks in the final content.
    """
    lines = content.split("\n")

    # First pass: remove consecutive blank lines, keeping max 1
    cleaned = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue  # Skip consecutive blank lines
        cleaned.append(line)
        prev_blank = is_blank

    # Join back and escape asterisks
    result = "\n".join(cleaned)
    result = _escape_asterisks(result)

    return result


def _ipv4_sort_key(cidr: str) -> tuple:
    """Sort key for IPv4 CIDR addresses (e.g., 172.20.20.10/24)."""
    if not cidr:
        return (999, 999, 999, 999, 0)

    try:
        ip_part = strip_cidr(cidr) or ""
        octets = tuple(int(x) for x in ip_part.split("."))
        return octets
    except (ValueError, AttributeError):
        return (999, 999, 999, 999)


def _dns_zone_sort_key(zone: str) -> tuple:
    """Sort key for DNS zones: letters before numbers, reverse zones by IP octets.

    Examples:
        - abhaile.home.arpa (0, 'abhaile.home.arpa')
        - svc.abhaile.home.arpa (0, 'svc.abhaile.home.arpa')
        - 20.20.172.in-addr.arpa (1, 172, 20, 20)
        - 100.20.172.in-addr.arpa (1, 172, 20, 100)
    """
    if zone.endswith(".in-addr.arpa"):
        # Reverse zone: extract octets and reverse for proper IP sorting
        octets_str = zone.replace(".in-addr.arpa", "")
        try:
            octets = [int(x) for x in octets_str.split(".")]
            # Reverse octets to get proper IP order (172.20.20 not 20.20.172)
            octets.reverse()
            return (1, *octets)  # Numbers sort after letters
        except (ValueError, AttributeError):
            return (1, 999, 999, 999)
    else:
        # Regular zone: alphabetical
        return (0, zone.lower())


def _md_table(rows: list[list[str]]) -> str:
    """Format rows as markdown table."""
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |\n"
    sep = "| " + " | ".join(["---"] * len(rows[0])) + " |\n"
    body = "".join("| " + " | ".join(r) + " |\n" for r in rows[1:])
    return header + sep + body


def format_inventory_markdown(
    network: dict[str, Any],
    deployments: dict[str, dict[str, list[str]]],
    dns_analysis: dict[str, Any] | None = None,
) -> str:
    """Format full inventory markdown using enriched network and deployments data.

    Automatically escapes asterisks and removes double blank lines.

    Args:
        network: Network configuration with vlans, hosts, services
        deployments: Host deployment mapping
        dns_analysis: Optional DNS zone analysis with internal/external counts
    """

    def build_service_hosts() -> dict[str, list[str]]:
        hosts: dict[str, list[str]] = {}
        for host_name, roles in deployments.items():
            for services in roles.values():
                for svc in services:
                    hosts.setdefault(svc, []).append(host_name)
        return {k: sorted(v) for k, v in hosts.items()}

    service_hosts = build_service_hosts()

    today = date.today().isoformat()
    vlans = network.get("vlans", {}) or {}
    hosts = network.get("hosts", {}) or {}
    services = network.get("services", {}) or {}

    md: list[str] = []
    md.append("# Abhaile Infrastructure Inventory")
    md.append("")
    md.append(
        f"Auto-generated from `config/mapping.yaml` and `config/network.yaml` (Updated: {today})"
    )
    md.append("")

    # Quick stats
    md.append("## Quick Stats")
    md.append("")
    md.append(f"- **Hosts:** {len(deployments)}")
    md.append(f"- **Deployed Services:** {len(service_hosts)}")
    md.append(f"- **VLANs:** {len(vlans)}")

    if dns_analysis:
        internal_count = dns_analysis.get("total_internal", 0)
        external_count = dns_analysis.get("total_external", 0)
        md.append(
            f"- **DNS Zones:** {internal_count} internal, {external_count} external"
        )

    md.append("")

    # Network topology
    md.append("## Network Topology")
    md.append("")

    if vlans:
        md.append("### VLANs")
        md.append("")
        rows = [["VLAN", "ID", "CIDR", "Gateway", "IPvlan L2 Range"]]
        # Sort VLANs by ID (numerical)
        for vlan_name in sorted(vlans.keys(), key=lambda v: vlans[v].get("id", 999)):
            v = vlans[vlan_name]
            rows.append(
                [
                    vlan_name,
                    str(v.get("id", "")),
                    v.get("cidr", ""),
                    v.get("gateway", ""),
                    v.get("ipvlanl2_range", ""),
                ]
            )
        md.append(_md_table(rows))
        md.append("")

    # DNS zones
    if dns_analysis:
        md.append("### DNS Zones")
        md.append("")

        internal = dns_analysis.get("internal", [])
        if internal:
            md.append("#### Internal Zones (CoreDNS)")
            md.append("")
            # Sort with letters before numbers, reverse zones by IP octets
            for zone in sorted(internal, key=_dns_zone_sort_key):
                md.append(f"- {zone}")
            md.append("")

        external = dns_analysis.get("external", [])
        if external:
            md.append("#### External Zones (deSEC)")
            md.append("")
            for zone in sorted(external, key=_dns_zone_sort_key):
                md.append(f"- {zone}")
            md.append("")

    # Hosts summary (preserve order from mapping.yaml)
    if hosts:
        md.append("## Hosts Summary")
        md.append("")
        # Use deployment order (mapping.yaml order) instead of alphabetical
        for host_name in deployments.keys():
            h = hosts[host_name]
            md.append(f"### {host_name}")
            md.append("")
            md.append(f"#### Network ({host_name})")
            md.append("")

            phys = h.get("physical_device", "-")
            md.append(f"Network Device: `{phys}`")
            md.append("")

            interfaces = h.get("interfaces", {}) or {}
            rows = [["Interface", "Address", "VLAN"]]
            sorted_interfaces = sorted(
                interfaces.items(),
                key=lambda x: _ipv4_sort_key(x[1].get("address", "")),
            )
            for iface_name, iface_data in sorted_interfaces:
                rows.append(
                    [
                        f"`{iface_name}`",
                        iface_data.get("address", ""),
                        iface_data.get("vlan", ""),
                    ]
                )
            md.append("Network Interfaces:")
            md.append("")
            md.append(_md_table(rows))
            md.append("")

            deployed = [
                svc
                for svc, host_list in service_hosts.items()
                if host_name in host_list
            ]
            md.append(f"#### Deployed Services ({host_name})")
            md.append("")
            if deployed:
                md.append(f"{len(deployed)} services deployed:")
                md.append("")
                for svc in sorted(deployed):
                    md.append(f"- {svc}")
            else:
                md.append("No services deployed.")
            md.append("")

    # Service catalog (superset: deployed + network-assigned)
    # Include all services that are either deployed OR have network config
    all_services = set(services.keys()) | set(service_hosts.keys())

    if all_services:
        md.append("## Service Catalog")
        md.append("")
        rows = [["Service", "Host", "VLAN", "IP"]]
        for svc_name in sorted(all_services):
            svc_def = services.get(svc_name, {}) or {}
            host_list = service_hosts.get(svc_name, [])
            # Preserve host order from mapping.yaml (deployments dict key order)
            ordered_hosts = [h for h in deployments.keys() if h in host_list]
            host = ", ".join(ordered_hosts) if ordered_hosts else "-"

            # Use VLAN from network config, or "-" if not defined
            vlan = svc_def.get("vlan", "") or "-"

            # Strip /32 from service addresses
            ip = strip_cidr(svc_def.get("address", "")) or "-"

            rows.append(
                [
                    svc_name,
                    host,
                    vlan,
                    ip,
                ]
            )

        md.append(_md_table(rows))
        md.append("")

    md.append("______________________________________________________________________")
    md.append("")
    md.append(
        "*Generated from `config/mapping.yaml` and `config/network.yaml` artifacts*"
    )
    md.append("")

    return _clean_markdown("\n".join(md))
