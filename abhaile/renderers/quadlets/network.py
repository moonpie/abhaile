"""Network quadlet helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from abhaile.renderers.quadlets.helpers import _validate_trailing_newline
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def _lookup_service_vlan(service: str, network: Dict[str, Any]) -> str:
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
    network: Dict[str, Any],
    vlans: List[str],
    output_dir: Path,
    config_root: Path,
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
        (output_base / f"{vlan_name}.network").write_text(
            rendered,
            encoding="utf-8",
            newline="\n",
        )
