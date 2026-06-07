"""CLI entrypoint for abhaile-inventory."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from abhaile.cli.common import configure_logging
from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import PipelineError, RenderError
from abhaile.utils.paths import get_repo_root, load_paths
from abhaile.validation.services import parse_mapping

LOG = logging.getLogger(__name__)


def parse_inventory_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-inventory."""
    parser = argparse.ArgumentParser(description="Print host-to-services inventory")
    parser.add_argument(
        "--format", choices=["table", "markdown", "json"], default="table", help="Output format"
    )
    parser.add_argument("--json", action="store_true", help="Alias for --format json")
    parser.add_argument("--output", type=Path, help="Write output to file instead of stdout")
    parser.add_argument("--validate", action="store_true", help="Check service definitions exist")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: info, -vv: debug)",
    )
    return parser.parse_args(argv)


def _load_config(config_root: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Load mapping and network config."""
    mapping = read_yaml_mapping(config_root / "mapping.yaml")
    network_path = config_root / "network.yaml"
    network: dict[str, Any] = read_yaml_mapping(network_path) if network_path.exists() else {}
    return parse_mapping(mapping), network


def _service_network_mode(service: str, config_root: Path) -> str:
    """Read network mode from service.yaml or return 'unknown'."""
    path = config_root / "services" / service / "service.yaml"
    if not path.exists():
        return "unknown"
    try:
        data = read_yaml_mapping(path)
    except (RenderError, Exception):
        return "unknown"
    if "podman" in data:
        return str(data["podman"].get("network", "none"))
    if "systemd" in data:
        return str(data["systemd"].get("network", "host-daemon"))
    return "none"


def _collect_service_access(
    network: dict[str, Any], config_root: Path, host_services: dict[str, list[str]]
) -> list[dict[str, str]]:
    """Collect user-facing FQDNs from CNAME records pointing through caddy."""
    access: list[dict[str, str]] = []
    services_net = network.get("services", {})
    deployed: set[str] = set()
    for svcs in host_services.values():
        deployed.update(svcs)
    ingress_services: set[str] = set()
    for svc in deployed:
        svc_path = config_root / "services" / svc / "service.yaml"
        if not svc_path.exists():
            continue
        try:
            data = read_yaml_mapping(svc_path)
        except Exception:
            continue
        if data.get("composition", {}).get("ingress"):
            ingress_services.add(svc)
    # Extract CNAMEs from abhaile.home.arpa. zone (user-facing aliases)
    for svc_name, svc_data in sorted(services_net.items()):
        for zone_entry in svc_data.get("dns", []):
            zone = zone_entry.get("zone", "")
            if zone != "abhaile.home.arpa.":
                continue
            for rec in zone_entry.get("records", []):
                if rec.get("type") != "cname":
                    continue
                fqdn = f"{rec['name']}.abhaile.home.arpa"
                rdata = rec.get("rdata", "")
                # CNAMEs pointing to caddy mean the service is ingress-fronted
                via_caddy = "caddy" in rdata
                access.append(
                    {
                        "fqdn": fqdn,
                        "service": svc_name,
                        "via_ingress": "yes" if via_caddy else "no",
                        "address": svc_data.get("address", "-"),
                    }
                )
    return access


def _build_inventory(config_root: Path) -> dict[str, Any]:
    """Build structured inventory data."""
    host_services, network = _load_config(config_root)
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hosts": host_services,
        "vlans": network.get("vlans", {}),
        "services_network": network.get("services", {}),
        "hosts_network": network.get("hosts", {}),
        "dns_zones": network.get("dns", {}).get("zones", []),
        "service_access": _collect_service_access(network, config_root, host_services),
    }


def _ip_sort_key(addr: str) -> tuple[int, ...]:
    """Sort key for IP/CIDR strings."""
    return tuple(ipaddress.ip_address(addr.split("/")[0]).packed)


def _render_markdown(inv: dict[str, Any], config_root: Path) -> str:
    """Render inventory as markdown."""
    lines: list[str] = ["# Abhaile Infrastructure Inventory\n"]
    lines.append(f"Generated: {inv['generated']}\n")
    # VLAN Summary
    lines.append("## VLAN Summary\n")
    lines.append("| VLAN | ID | CIDR | Gateway | ipvlan-l2 Range |")
    lines.append("|------|----|------|---------|-----------------|")
    for name in sorted(inv["vlans"], key=lambda n: inv["vlans"][n].get("id", 0)):
        v = inv["vlans"][name]
        lines.append(
            f"| {name} | {v.get('id', '-')} | {v.get('cidr', '-')} "
            f"| {v.get('gateway', '-')} | {v.get('ipvlanl2_range', '-')} |"
        )
    lines.append("")
    # Hosts
    lines.append("## Hosts\n")
    for host in sorted(inv["hosts_network"]):
        lines.append(f"### {host}\n")
        lines.append("| Interface | Address | VLAN |")
        lines.append("|-----------|---------|------|")
        ifaces = inv["hosts_network"][host].get("interfaces", {})
        for iface in sorted(ifaces):
            d = ifaces[iface]
            lines.append(f"| {iface} | {d.get('address', '-')} | {d.get('vlan', '-')} |")
        lines.append("")
    # Services by Host
    lines.append("## Services by Host\n")
    for host in sorted(inv["hosts"]):
        services = inv["hosts"][host]
        lines.append(f"### {host} ({len(services)} services)\n")
        lines.append("| Service | Address | VLAN | Network Mode |")
        lines.append("|---------|---------|------|--------------|")
        for svc in inv["hosts"][host]:
            svc_net = inv["services_network"].get(svc, {})
            mode = _service_network_mode(svc, config_root)
            lines.append(
                f"| {svc} | {svc_net.get('address', '-')} | {svc_net.get('vlan', '-')} | {mode} |"
            )
        lines.append("")
    # Address Allocation
    lines.append("## Address Allocation\n")
    lines.append("| Address | Service/Host | VLAN |")
    lines.append("|---------|--------------|------|")
    all_addrs: list[tuple[str, str, str]] = []
    for svc, data in inv["services_network"].items():
        if "address" in data:
            all_addrs.append((data["address"], svc, data.get("vlan", "-")))
    for host, hdata in inv["hosts_network"].items():
        for iface, idata in hdata.get("interfaces", {}).items():
            if "address" in idata:
                all_addrs.append((idata["address"], f"{host}/{iface}", idata.get("vlan", "-")))
    all_addrs.sort(key=lambda t: _ip_sort_key(t[0]))
    for addr, name, vlan in all_addrs:
        lines.append(f"| {addr} | {name} | {vlan} |")
    lines.append("")
    # DNS Summary
    lines.append("## DNS Zones\n")
    lines.append("| Zone | Type | Provider |")
    lines.append("|------|------|----------|")
    for zone in sorted(inv["dns_zones"], key=lambda z: z.get("name", "")):
        prov = zone.get("provider", {})
        lines.append(
            f"| {zone.get('name', '-')} | {prov.get('type', '-')} " f"| {prov.get('name', '-')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_table(inv: dict[str, Any]) -> str:
    """Render inventory as plain text table."""
    lines: list[str] = []
    for host in sorted(inv["hosts"]):
        lines.append(f"{host}:")
        for svc in inv["hosts"][host]:
            lines.append(f"  {svc}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-inventory."""
    args = parse_inventory_args(argv)
    configure_logging(args.verbose)
    fmt = "json" if args.json else args.format

    repo_root = get_repo_root(Path(__file__))
    paths = load_paths(repo_root)
    config_root = repo_root / paths["config_root"]

    if args.validate:
        host_services, _ = _load_config(config_root)
        missing: list[str] = []
        seen: set[str] = set()
        for services in host_services.values():
            for svc in services:
                if svc in seen:
                    continue
                seen.add(svc)
                if not (config_root / "services" / svc / "service.yaml").exists():
                    missing.append(str(config_root / "services" / svc / "service.yaml"))
        if missing:
            for p in sorted(missing):
                print(f"missing: {p}", file=sys.stderr)
            return 1

    inv = _build_inventory(config_root)
    if fmt == "json":
        output = json.dumps({host: inv["hosts"][host] for host in sorted(inv["hosts"])}, indent=2)
    elif fmt == "markdown":
        output = _render_markdown(inv, config_root)
    else:
        output = _render_table(inv)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        LOG.info("inventory.written path=%s", args.output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"inventory: {exc}", file=sys.stderr)
        sys.exit(1)
