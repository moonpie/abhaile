"""Network configuration sanity checks: VLANs, IP ranges, collisions."""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from typing import Any, Dict, List

# Import errors from utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.errors import RenderError


def validate_network_sanity(network: Dict[str, Any]) -> None:
    """Validate network configuration for VLAN/IP consistency.

    Checks:
    - VLAN references exist
    - Host interfaces are within their VLAN's CIDR
    - Service addresses are within their VLAN's CIDR
    - Service /32 addresses are within ipvlanl2_range
    - No duplicate IPs across hosts/services

    Args:
        network: Network configuration from network.yaml.

    Raises:
        RenderError: If any validation fails.
    """
    errors: List[str] = []
    vlans = network.get("vlans", {})

    def vlan_net(vlan_name: str):
        vlan = vlans.get(vlan_name)
        if not vlan:
            return None
        return ipaddress.ip_network(vlan["cidr"], strict=False)

    def vlan_range(vlan_name: str):
        vlan = vlans.get(vlan_name)
        if not vlan:
            return None
        ipr = vlan.get("ipvlanl2_range")
        if not ipr:
            return None
        start_s, end_s = ipr.split("-", 1)
        return ipaddress.ip_address(start_s), ipaddress.ip_address(end_s)

    # Host interface checks
    hosts = network.get("hosts", {})
    for host, host_data in hosts.items():
        interfaces = host_data.get("interfaces", {})
        for ifname, ifdata in interfaces.items():
            vlan = ifdata.get("vlan")
            addr = ifdata.get("address")
            if vlan not in vlans:
                errors.append(
                    f"Host {host} interface {ifname} references unknown vlan '{vlan}'"
                )
                continue
            if addr:
                ip = ipaddress.ip_interface(addr).ip
                net = vlan_net(vlan)
                if net and ip not in net:
                    errors.append(
                        f"Host {host} interface {ifname} address {addr} not in vlan {vlan} {net}"
                    )

    # Service checks
    services = network.get("services", {})
    for svc, svc_data in services.items():
        vlan = svc_data.get("vlan")
        addr = svc_data.get("address")
        if vlan not in vlans:
            errors.append(f"Service {svc} references unknown vlan '{vlan}'")
            continue
        if addr:
            ip = ipaddress.ip_interface(addr).ip
            net = vlan_net(vlan)
            if net and ip not in net:
                errors.append(f"Service {svc} address {addr} not in vlan {vlan} {net}")
            vr = vlan_range(vlan)
            if vr and not (vr[0] <= ip <= vr[1]):
                errors.append(
                    f"Service {svc} address {addr} not in ipvlanl2_range {vr[0]}-{vr[1]}"
                )

    # Address collision checks
    ip_map: Dict[str, List[str]] = {}

    def add_ip(owner: str, addr: str | None) -> None:
        if not addr:
            return
        ip = str(ipaddress.ip_interface(addr).ip)
        ip_map.setdefault(ip, []).append(owner)

    for host, host_data in hosts.items():
        for ifname, ifdata in host_data.get("interfaces", {}).items():
            add_ip(f"host:{host}:{ifname}", ifdata.get("address"))

    for svc, svc_data in services.items():
        add_ip(f"service:{svc}", svc_data.get("address"))

    for ip, owners in ip_map.items():
        if len(owners) > 1:
            errors.append(f"Duplicate IP {ip} used by {', '.join(owners)}")

    if errors:
        formatted = "\n".join(f"- {err}" for err in errors)
        raise RenderError(f"Network sanity checks failed:\n{formatted}")


def validate_host_physical_device(
    host: str, host_config: Dict[str, Any], network: Dict[str, Any]
) -> None:
    """Validate that host's physical_device is defined in network.yaml.

    Args:
        host: Host name (e.g., phobos, deimos).
        host_config: Host configuration from host.yaml.
        network: Network configuration from network.yaml.

    Raises:
        RenderError: If physical_device is specified but not found in network.yaml
                     host interfaces, or if validation otherwise fails.
    """
    physical_device = host_config.get("physical_device")
    if not physical_device:
        return  # physical_device is optional (e.g., common host.yaml)

    hosts = network.get("hosts", {})
    if host not in hosts:
        raise RenderError(
            f"Host '{host}' not found in network.yaml; cannot validate physical_device"
        )

    host_interfaces = hosts[host].get("interfaces", {})
    if physical_device not in host_interfaces:
        raise RenderError(
            f"Host '{host}' physical_device '{physical_device}' not found in network.yaml interfaces. "
            f"Available interfaces: {', '.join(sorted(host_interfaces.keys()))}"
        )
