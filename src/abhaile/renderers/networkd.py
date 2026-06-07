"""Systemd-networkd renderer for host network configurations."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from jinja2 import TemplateError, TemplateNotFound, UndefinedError

from abhaile.utils.errors import RenderError
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.config import read_yaml
from abhaile.utils.network import strip_cidr
from abhaile.utils.templating import create_jinja_env
from abhaile.renderers.config import (
    filter_config_entries_by_destination_prefix,
    render_config_entries,
)


def render_networkd_config(
    host: str,
    host_config: dict[str, Any],
    common_config: dict[str, Any],
    network: dict[str, Any],
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render systemd-networkd configuration files for a host.

    Processes composition.config entries with destinations under /etc/systemd/network/
    from both common and host-specific configurations.
    """
    output_networkd_dir = output_dir / "etc/systemd/network"
    output_networkd_dir.mkdir(parents=True, exist_ok=True)

    # Jinja2 context for templates
    context = {
        "network": network,
        "host_name": host,
    }

    # Process common first (implicit include)
    common_entries = common_config.get("composition", {}).get("config", [])
    networkd_common = filter_config_entries_by_destination_prefix(
        common_entries,
        "/etc/systemd/network/",
        include=True,
    )

    render_config_entries(
        networkd_common,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
        collector=collector,
        rendered_root=rendered_root,
        default_owner_ref=f"host:{host}",
    )

    # Process host-specific (overrides/adds to common)
    host_entries = host_config.get("composition", {}).get("config", [])
    networkd_host = filter_config_entries_by_destination_prefix(
        host_entries,
        "/etc/systemd/network/",
        include=True,
    )

    render_config_entries(
        networkd_host,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
        collector=collector,
        rendered_root=rendered_root,
        default_owner_ref=f"host:{host}",
    )

    _register_networkd_owners(
        collector,
        host=host,
        host_config=host_config,
        network=network,
    )


def render_networkd_dropins(
    host: str,
    host_services: list[str],
    network: dict[str, Any],
    config_root: Path,
    output_networkd_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render service drop-in files for systemd-networkd.

    Drop-ins are rendered only for services mapped to the host in mapping.yaml
    and only for services whose service.yaml has network: service-32 or ipvlan-l2.

    The drop-in is placed under the .network.d/ directory for the interface on the
    same VLAN as the service address in network.yaml.
    """
    if not host_services:
        return

    dropin_dirs_by_vlan = _get_dropin_dirs_by_vlan(host, network, output_networkd_dir)

    templates_dir = config_root / "_templates" / "hosts"
    jinja_env = create_jinja_env(templates_dir)

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
            raise RenderError(f"Service '{service_name}' missing from network.yaml services")

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
            "service-addr.conf.j2" if network_mode == "service-32" else "service-route.conf.j2"
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
        except (TemplateError, TemplateNotFound, UndefinedError) as exc:
            raise RenderError(
                f"Failed to render drop-in template {template_name} for service '{service_name}': {exc}"
            ) from exc

        service_address = service_info.get("address")
        if not service_address:
            raise RenderError(f"Service '{service_name}' missing address in network.yaml")

        last_octet = _get_last_octet(service_address)
        output_filename = f"{last_octet:03d}-{service_name}.conf"
        output_path = dropin_dir / output_filename
        output_path.write_text(rendered_content, encoding="utf-8", newline="\n")

        _register_networkd_dropin_artifact(
            collector=collector,
            rendered_root=rendered_root,
            output_path=output_path,
            interface_name=interface_name,
            content=rendered_content,
        )


def _get_dropin_dirs_by_vlan(
    host: str,
    network: dict[str, Any],
    output_networkd_dir: Path,
) -> dict[str, Path]:
    """Return drop-in directories keyed by VLAN name.

    Raises RenderError if multiple drop-in directories map to the same VLAN.
    """
    host_interfaces = network.get("hosts", {}).get(host, {}).get("interfaces", {})
    interface_vlans = {name: data.get("vlan") for name, data in host_interfaces.items() if data}

    # If output directory doesn't exist yet, return empty dict (error will be raised when service checks for VLAN)
    if not output_networkd_dir.exists():
        return {}

    dropin_dirs = [
        path
        for path in output_networkd_dir.iterdir()
        if path.is_dir() and path.name.endswith(".network.d")
    ]

    dropins_by_vlan: dict[str, list[Path]] = {}
    for dropin_dir in dropin_dirs:
        interface_name = _interface_from_base_file(output_networkd_dir, dropin_dir)
        if interface_name not in interface_vlans:
            raise RenderError(
                f"Drop-in directory '{dropin_dir.name}' references unknown interface '{interface_name}' on host '{host}'"
            )
        vlan = interface_vlans[interface_name]
        if not vlan:
            raise RenderError(f"Interface '{interface_name}' missing vlan on host '{host}'")
        dropins_by_vlan.setdefault(vlan, []).append(dropin_dir)

    for vlan, dirs in dropins_by_vlan.items():
        if len(dirs) > 1:
            formatted = ", ".join(sorted(d.name for d in dirs))
            raise RenderError(
                f"Multiple drop-in directories for vlan '{vlan}' on host '{host}': {formatted}"
            )

    return {vlan: dirs[0] for vlan, dirs in dropins_by_vlan.items()}


def _interface_from_base_file(output_networkd_dir: Path, dropin_dir: Path) -> str:
    """Extract interface name from the [Match] Name= field of the base .network file.

    Example: 21-ipvlan-l2.network.d -> reads 21-ipvlan-l2.network -> [Match] Name=ipvlan-l2
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
    except (OSError, PermissionError) as exc:
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

    raise RenderError(f"Could not find 'Name=' in [Match] section of base file '{base_name}'")


def _get_last_octet(address: str) -> int:
    """Return last octet of an IPv4 address, stripping CIDR if present."""
    ip_str = strip_cidr(address)
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError as exc:
        raise RenderError(f"Invalid IP address '{address}'") from exc

    if ip.version != 4:
        raise RenderError(f"Only IPv4 addresses supported for drop-in naming: {address}")

    return int(str(ip).split(".")[-1])


def _register_networkd_dropin_artifact(
    *,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
    output_path: Path,
    interface_name: str,
    content: str,
) -> None:
    """Register rendered networkd drop-in metadata when collection is enabled."""
    if collector is None or rendered_root is None:
        return

    render_path = output_path.relative_to(rendered_root).as_posix()
    target_path = _target_path_from_render_path(render_path)
    owner_ref = f"iface:{interface_name}"

    collector.register_artifact(
        render_path=render_path,
        target_path=target_path,
        kind="networkd.dropin",
        owner_ref=owner_ref,
        content=content,
        replace=True,
    )
    _ensure_networkd_owner(collector, owner_ref)


def _register_networkd_owners(
    collector: ArtifactCollector | None,
    *,
    host: str,
    host_config: dict[str, Any],
    network: dict[str, Any],
) -> None:
    """Register interface owners for collected networkd artifacts."""
    if collector is None:
        return

    requires_by_iface = _build_requires_by_iface(
        host=host, host_config=host_config, network=network
    )

    for artifact in collector.get_all_artifacts():
        if not artifact.kind.startswith("networkd."):
            continue
        _ensure_networkd_owner(collector, artifact.owner_ref, requires_by_iface=requires_by_iface)


def _build_requires_by_iface(
    *,
    host: str,
    host_config: dict[str, Any],
    network: dict[str, Any],
) -> dict[str, list[str]]:
    """Build requires edges for host interfaces from network topology.

    For this repo's network model, ipvlan interfaces are children of a host's
    physical uplink (or VLAN subinterface for dotted names). VLAN interfaces are
    children of their base interface.
    """
    requires_by_iface: dict[str, list[str]] = {}

    host_interfaces = network.get("hosts", {}).get(host, {}).get("interfaces", {})
    if not isinstance(host_interfaces, dict):
        return requires_by_iface

    physical_device = host_config.get("physical_device")
    if not isinstance(physical_device, str) or not physical_device:
        physical_device = None

    for iface in host_interfaces:
        if not isinstance(iface, str) or not iface:
            continue

        requires: list[str] = []

        if iface.startswith("ipvlan-l2") and physical_device:
            suffix = iface[len("ipvlan-l2") :]
            parent_iface = f"{physical_device}{suffix}"
            if parent_iface in host_interfaces:
                requires.append(f"iface:{parent_iface}")
            elif suffix:
                requires.append(f"iface:{physical_device}")
            else:
                requires.append(f"iface:{physical_device}")
        elif "." in iface:
            parent_iface = iface.rsplit(".", 1)[0]
            requires.append(f"iface:{parent_iface}")

        requires_by_iface[iface] = sorted(set(requires))

    return requires_by_iface


def _ensure_networkd_owner(
    collector: ArtifactCollector,
    owner_ref: str,
    *,
    requires_by_iface: dict[str, list[str]] | None = None,
) -> None:
    """Register owner metadata for a network interface if not present."""
    if not owner_ref.startswith("iface:"):
        return

    owners = collector.get_all_owners()
    if owner_ref in owners:
        return

    iface = owner_ref.split(":", 1)[1]
    requires: list[str]
    if requires_by_iface is not None and iface in requires_by_iface:
        requires = list(requires_by_iface.get(iface, []))
    else:
        requires = []
        if "." in iface:
            parent_iface = iface.rsplit(".", 1)[0]
            requires.append(f"iface:{parent_iface}")

    collector.register_owner(
        name=owner_ref,
        description=f"systemd-networkd interface {iface}",
        requires=requires,
    )


def _target_path_from_render_path(render_path: str) -> str:
    """Map render path to target path for networkd artifact registration."""
    if render_path.startswith("system/"):
        return f"/{render_path[len('system/') :]}"
    return f"/{render_path.lstrip('/')}"
