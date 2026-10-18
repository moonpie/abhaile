"""Network configuration sanity checks: VLANs, IP ranges, collisions."""

from __future__ import annotations

import ipaddress
from typing import Any

from abhaile.utils.errors import RenderError


def validate_network_sanity(network: dict[str, Any]) -> None:
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
    errors: list[str] = []
    vlans = network.get("vlans", {})

    def vlan_net(
        vlan_name: str,
    ) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
        """Return the IP network for a VLAN, if defined."""
        vlan = vlans.get(vlan_name)
        if not vlan:
            return None
        return ipaddress.ip_network(vlan["cidr"], strict=False)

    def vlan_range(
        vlan_name: str,
    ) -> (
        tuple[
            ipaddress.IPv4Address | ipaddress.IPv6Address,
            ipaddress.IPv4Address | ipaddress.IPv6Address,
        ]
        | None
    ):
        """Return the IPvlan L2 range for a VLAN, if configured."""
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
                errors.append(f"Host {host} interface {ifname} references unknown vlan '{vlan}'")
                continue
            if addr:
                ip = ipaddress.ip_interface(addr).ip
                net = vlan_net(vlan)
                if net and ip not in net:
                    errors.append(
                        f"Host {host} interface {ifname} address {addr} not in vlan {vlan} {net}"
                    )
            try:
                normalize_convergence_probes(host, ifname, network)
            except RenderError as exc:
                errors.append(str(exc))

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
            if vr:
                start, end = vr
                if ip.version != start.version or ip.version != end.version:
                    errors.append(
                        f"Service {svc} address {addr} IP version mismatch with ipvlanl2_range {start}-{end}"
                    )
                else:
                    if (
                        isinstance(ip, ipaddress.IPv4Address)
                        and isinstance(start, ipaddress.IPv4Address)
                        and isinstance(end, ipaddress.IPv4Address)
                    ):
                        if not (start <= ip <= end):
                            errors.append(
                                f"Service {svc} address {addr} not in ipvlanl2_range {start}-{end}"
                            )
                    elif (
                        isinstance(ip, ipaddress.IPv6Address)
                        and isinstance(start, ipaddress.IPv6Address)
                        and isinstance(end, ipaddress.IPv6Address)
                    ):
                        if not (start <= ip <= end):
                            errors.append(
                                f"Service {svc} address {addr} not in ipvlanl2_range {start}-{end}"
                            )

    # Address collision checks
    ip_map: dict[str, list[str]] = {}

    def add_ip(owner: str, addr: str | None) -> None:
        """Record an owner for an IP address in the collision map."""
        if not addr:
            return
        ip = str(ipaddress.ip_interface(addr).ip)
        ip_map.setdefault(ip, []).append(owner)

    for host, host_data in hosts.items():
        for ifname, ifdata in host_data.get("interfaces", {}).items():
            add_ip(f"host:{host}:{ifname}", ifdata.get("address"))

    for svc, svc_data in services.items():
        add_ip(f"service:{svc}", svc_data.get("address"))

    for ip_str, owners in ip_map.items():
        if len(owners) > 1:
            errors.append(f"Duplicate IP {ip_str} used by {', '.join(owners)}")

    if errors:
        formatted = "\n".join(f"- {err}" for err in errors)
        raise RenderError(f"Network sanity checks failed:\n{formatted}")


def normalize_convergence_probes(
    host: str, interface: str, network: dict[str, Any]
) -> list[dict[str, object]]:
    """Normalize explicit interface probe intent into sealed literal authority."""
    try:
        ifdata = network["hosts"][host]["interfaces"][interface]
        address = ipaddress.ip_interface(ifdata["address"])
        vlan_name = ifdata["vlan"]
        vlan = network["vlans"][vlan_name]
        subnet = ipaddress.ip_network(vlan["cidr"], strict=False)
        configured = ifdata.get("convergence_probes", [])
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderError(f"Invalid convergence probe owner {host}:{interface}") from exc
    if not configured:
        return []
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_semantics: set[tuple[object, ...]] = set()
    has_peer = False
    for raw in configured:
        if not isinstance(raw, dict):
            raise RenderError(f"Invalid convergence probe for {host}:{interface}")
        probe_id = raw.get("id")
        probe_type = raw.get("type")
        if not isinstance(probe_id, str) or probe_id in seen_ids:
            raise RenderError(f"Duplicate convergence probe id for {host}:{interface}")
        seen_ids.add(probe_id)
        target_value = vlan.get("gateway") if probe_type == "gateway" else raw.get("address")
        if not isinstance(target_value, (str, int, bytes)):
            raise RenderError(f"Invalid convergence probe target for {host}:{interface}")
        try:
            target = ipaddress.ip_address(target_value)
        except (TypeError, ValueError) as exc:
            raise RenderError(f"Invalid convergence probe target for {host}:{interface}") from exc
        if (
            target.version != address.version
            or target == address.ip
            or target.is_unspecified
            or target.is_multicast
            or target.is_loopback
            or target.is_link_local
            or (probe_type == "gateway" and target not in subnet)
            or target in {subnet.network_address, subnet.broadcast_address}
        ):
            raise RenderError(f"Unsafe convergence probe target for {host}:{interface}")
        transport = "icmp" if probe_type in {"gateway", "icmp"} else "tcp-peer"
        port = raw.get("port") if probe_type == "external-peer" else None
        semantic = (transport, str(target), port)
        if semantic in seen_semantics:
            raise RenderError(f"Duplicate convergence probe for {host}:{interface}")
        seen_semantics.add(semantic)
        has_peer = has_peer or probe_type == "external-peer"
        normalized.append(
            {
                "id": probe_id,
                "type": probe_type,
                "transport": transport,
                "host": host,
                "interface": interface,
                "owner_ref": f"iface:{interface}",
                "source": str(address.ip),
                "prefix": address.network.prefixlen,
                "vlan": vlan_name,
                "target": str(target),
                "port": port,
                "required": True,
            }
        )
    if not has_peer:
        raise RenderError(f"Convergence probes for {host}:{interface} lack an external peer")
    return sorted(normalized, key=lambda probe: str(probe["id"]))


def validate_host_physical_device(
    host: str, host_config: dict[str, Any], network: dict[str, Any]
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
