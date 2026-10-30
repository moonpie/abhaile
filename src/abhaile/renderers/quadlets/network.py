"""Network quadlet helpers."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any

from abhaile.renderers.quadlets.helpers import (
    _quadlet_kind_from_filename,
    _quadlet_unit_name,
    _register_quadlet_artifact,
    _validate_trailing_newline,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def _lookup_service_vlan(service: str, network: dict[str, Any]) -> str:
    """Return the VLAN name for a service from network.yaml."""
    service_def = network.get("services", {}).get(service)
    if not service_def:
        raise RenderError(f"Missing network.services entry for service '{service}'")
    vlan = service_def.get("vlan")
    if not vlan:
        raise RenderError(f"Missing VLAN for service '{service}'")
    if not isinstance(vlan, str):
        raise RenderError(f"Invalid VLAN for service '{service}': {vlan}")
    return vlan


def _render_network_quadlets(
    host: str,
    network: dict[str, Any],
    vlans: list[str],
    output_dir: Path,
    config_root: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render network quadlet files for the provided VLAN list."""
    template_path = config_root / "_templates" / "services" / "quadlets" / "network.network.j2"
    if not template_path.exists():
        raise RenderError(f"Missing network template: {template_path}")
    _validate_trailing_newline(
        template_path,
        context="quadlet network template",
    )

    output_root = Path("/etc/containers/systemd")
    output_root_relative = output_root.as_posix().lstrip("/")
    output_base = output_dir / output_root_relative
    output_base.mkdir(parents=True, exist_ok=True)

    jinja_env = create_jinja_env(template_path.parent)

    template = jinja_env.get_template(template_path.name)

    for vlan_name in vlans:
        rendered = template.render(
            network=network,
            host_name=host,
            vlan_name=vlan_name,
        )
        network_filename = f"{vlan_name}.network"
        network_path = output_base / network_filename
        network_path.write_text(
            rendered,
            encoding="utf-8",
            newline="\n",
        )
        if collector is not None and rendered_root is not None:
            vlan = network["vlans"][vlan_name]
            interface = next(
                (
                    name
                    for name, definition in network["hosts"][host]["interfaces"].items()
                    if definition["vlan"] == vlan_name and not name.startswith("ipvlan-")
                ),
                "",
            )
            subnet: dict[str, Any] = {"subnet": vlan["cidr"], "gateway": vlan["gateway"]}
            if vlan.get("ipvlanl2_range"):
                ip_range = vlan["ipvlanl2_range"]
                if "-" in ip_range:
                    first, last = ip_range.split("-", maxsplit=1)
                    start_ip, end_ip = str(ip_address(first.strip())), str(ip_address(last.strip()))
                else:
                    addresses = ip_network(ip_range, strict=False)
                    start_ip = str(next(iter(addresses.hosts())))
                    end_ip = str(
                        addresses.broadcast_address
                        - (1 if addresses.version == 4 and addresses.num_addresses > 2 else 0)
                    )
                subnet["lease_range"] = {"start_ip": start_ip, "end_ip": end_ip}
            hints = {
                "rootless": False,
                "shared": True,
                "podman_resource": {
                    "name": f"systemd-{vlan_name}",
                    "driver": "ipvlan",
                    "network_interface": interface,
                    "subnets": [subnet],
                    "options": {"mode": "l2"},
                    "internal": False,
                    "dns_enabled": False,
                    "ipv6_enabled": ip_network(vlan["cidr"], strict=False).version == 6,
                    "ipam_options": {"driver": "host-local"},
                },
            }
            _register_quadlet_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=network_path,
                target_path=str(output_root / network_filename),
                kind=_quadlet_kind_from_filename(network_filename),
                owner_ref=f"unit:{_quadlet_unit_name(network_filename)}",
                content=rendered,
                apply_hints=hints,
                owner_apply_hints=hints,
            )
