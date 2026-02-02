"""Systemd-networkd renderer for host network configurations."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.errors import RenderError
from utils.config import read_yaml
from renderers.config import render_config_entries


def _strip_cidr(address: str) -> str:
    """Jinja2 filter to strip CIDR notation from IP address.

    Args:
        address: IP address with CIDR (e.g., "172.20.20.10/24")

    Returns:
        IP address without CIDR (e.g., "172.20.20.10")
    """
    return address.split("/")[0] if "/" in address else address


def render_networkd_config(
    host: str,
    host_config: Dict[str, Any],
    common_config: Dict[str, Any],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render systemd-networkd configuration files for a host.

    Processes composition.config entries with destinations under /etc/systemd/network/
    from both common and host-specific configurations.

    Args:
        host: Host name (e.g., phobos, deimos).
        host_config: Host configuration from config/hosts/<host>/host.yaml.
        common_config: Common configuration from config/hosts/common/host.yaml.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_dir: Path to output root (entries render relative to this).

    Raises:
        RenderError: If source file/template missing or rendering fails.
    """
    output_networkd_dir = output_dir / "etc/systemd/network"
    output_networkd_dir.mkdir(parents=True, exist_ok=True)

    # Jinja2 context for templates
    context = {
        "network": network,
        "host_name": host,
    }

    # Filter config entries for systemd-networkd (destination starts with /etc/systemd/network/)
    def is_networkd_entry(entry: Dict[str, Any]) -> bool:
        dest = entry.get("destination", "")
        return dest.startswith("/etc/systemd/network/")

    # Process common first (implicit include)
    common_entries = common_config.get("composition", {}).get("config", [])
    networkd_common = [e for e in common_entries if is_networkd_entry(e)]

    render_config_entries(
        networkd_common,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
    )

    # Process host-specific (overrides/adds to common)
    host_entries = host_config.get("composition", {}).get("config", [])
    networkd_host = [e for e in host_entries if is_networkd_entry(e)]

    render_config_entries(
        networkd_host,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
    )


def render_networkd_dropins(
    host: str,
    host_services: list[str],
    network: Dict[str, Any],
    config_root: Path,
    output_networkd_dir: Path,
) -> None:
    """Render service drop-in files for systemd-networkd.

    Drop-ins are rendered only for services mapped to the host in mapping.yaml
    and only for services whose service.yaml has network: service-32 or ipvlan-l2.

    The drop-in is placed under the .network.d/ directory for the interface on the
    same VLAN as the service address in network.yaml.

    Args:
        host: Host name (e.g., phobos, deimos).
        host_services: Service names mapped to this host.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_networkd_dir: Path to <output>/rendered/systemd-networkd/.

    Raises:
        RenderError: If drop-in selection is ambiguous or configuration is missing.
    """
    if not host_services:
        return

    dropin_dirs_by_vlan = _get_dropin_dirs_by_vlan(host, network, output_networkd_dir)

    templates_dir = config_root / "_templates" / "hosts"
    jinja_env = Environment(
        loader=FileSystemLoader(templates_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

    for service in host_services:
        service_path = config_root / "services" / service / "service.yaml"
        service_data = read_yaml(service_path)
        service_name = service_data.get("name", service)

        # Determine network mode from new schema structure
        network_mode = None
        if "podman" in service_data:
            network_mode = service_data["podman"].get("network", "")
        elif "systemd" in service_data:
            network_mode = service_data["systemd"].get("network", "")

        if network_mode not in {"service-32", "ipvlan-l2"}:
            continue

        service_info = network.get("services", {}).get(service_name)
        if not service_info:
            raise RenderError(
                f"Service '{service_name}' missing from network.yaml services"
            )

        service_vlan = service_info.get("vlan")
        if not service_vlan:
            raise RenderError(f"Service '{service_name}' missing vlan in network.yaml")

        dropin_dir = dropin_dirs_by_vlan.get(service_vlan)
        if not dropin_dir:
            raise RenderError(
                f"No drop-in directory found for vlan '{service_vlan}' on host '{host}'"
            )

        interface_name = _interface_from_base_file(output_networkd_dir, dropin_dir)

        template_name = (
            "service-addr.conf.j2"
            if network_mode == "service-32"
            else "service-route.conf.j2"
        )

        try:
            template = jinja_env.get_template(template_name)
            rendered_content = template.render(
                network=network,
                host_name=host,
                service_name=service_name,
                service_address=service_info.get("address"),
                interface_name=interface_name,
            )
        except Exception as exc:
            raise RenderError(
                f"Failed to render drop-in template {template_name} for service '{service_name}': {exc}"
            ) from exc

        service_address = service_info.get("address")
        if not service_address:
            raise RenderError(
                f"Service '{service_name}' missing address in network.yaml"
            )

        last_octet = _get_last_octet(service_address)
        output_filename = f"{last_octet:03d}-{service_name}.conf"
        output_path = dropin_dir / output_filename
        output_path.write_text(rendered_content)


def _get_dropin_dirs_by_vlan(
    host: str,
    network: Dict[str, Any],
    output_networkd_dir: Path,
) -> Dict[str, Path]:
    """Return drop-in directories keyed by VLAN name.

    Raises RenderError if multiple drop-in directories map to the same VLAN.
    """
    host_interfaces = network.get("hosts", {}).get(host, {}).get("interfaces", {})
    interface_vlans = {
        name: data.get("vlan") for name, data in host_interfaces.items() if data
    }

    # If output directory doesn't exist yet, return empty dict (error will be raised when service checks for VLAN)
    if not output_networkd_dir.exists():
        return {}

    dropin_dirs = [
        path
        for path in output_networkd_dir.iterdir()
        if path.is_dir() and path.name.endswith(".network.d")
    ]

    dropins_by_vlan: Dict[str, list[Path]] = {}
    for dropin_dir in dropin_dirs:
        interface_name = _interface_from_base_file(output_networkd_dir, dropin_dir)
        if interface_name not in interface_vlans:
            raise RenderError(
                f"Drop-in directory '{dropin_dir.name}' references unknown interface '{interface_name}' on host '{host}'"
            )
        vlan = interface_vlans[interface_name]
        if not vlan:
            raise RenderError(
                f"Interface '{interface_name}' missing vlan on host '{host}'"
            )
        dropins_by_vlan.setdefault(vlan, []).append(dropin_dir)

    for vlan, dirs in dropins_by_vlan.items():
        if len(dirs) > 1:
            formatted = ", ".join(sorted(d.name for d in dirs))
            raise RenderError(
                f"Multiple drop-in directories for vlan '{vlan}' on host '{host}': {formatted}"
            )

    return {vlan: dirs[0] for vlan, dirs in dropins_by_vlan.items()}


def _interface_from_base_file(output_networkd_dir: Path, dropin_dir: Path) -> str:
    """Extract interface name from the base file corresponding to a drop-in directory.

    The base file is the drop-in directory name with .d suffix removed.
    The interface name is extracted from the [Match] Name= field in the base file.

    Example: 21-ipvlan-l2.network.d -> reads 21-ipvlan-l2.network -> [Match] Name=ipvlan-l2

    Args:
        output_networkd_dir: Path to systemd-networkd output directory.
        dropin_dir: Drop-in directory path.

    Returns:
        Interface name from [Match] Name= field.

    Raises:
        RenderError: If base file missing, invalid format, or Name= not found.
    """
    dropin_name = dropin_dir.name
    if not dropin_name.endswith(".d"):
        raise RenderError(f"Invalid drop-in directory name: {dropin_name}")

    base_name = dropin_name[:-2]  # Strip .d suffix
    base_file = output_networkd_dir / base_name

    if not base_file.exists():
        raise RenderError(
            f"Drop-in directory '{dropin_name}' missing corresponding base file '{base_name}'"
        )

    try:
        content = base_file.read_text()
    except Exception as exc:
        raise RenderError(f"Failed to read base file '{base_name}': {exc}") from exc

    # Look for [Match] section with Name= field
    in_match_section = False
    for line in content.split("\n"):
        line = line.strip()
        if line == "[Match]":
            in_match_section = True
            continue
        if in_match_section and line.startswith("["):
            # End of [Match] section without finding Name=
            break
        if in_match_section and line.startswith("Name="):
            return line.split("=", 1)[1].strip()

    raise RenderError(
        f"Could not find 'Name=' in [Match] section of base file '{base_name}'"
    )


def _get_last_octet(address: str) -> int:
    """Return last octet of an IPv4 address, stripping CIDR if present."""
    ip_str = _strip_cidr(address)
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError as exc:
        raise RenderError(f"Invalid IP address '{address}'") from exc

    if ip.version != 4:
        raise RenderError(
            f"Only IPv4 addresses supported for drop-in naming: {address}"
        )

    return int(str(ip).split(".")[-1])
