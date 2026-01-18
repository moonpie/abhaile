"""Networkd builder (pure, no writes).

Returns a list of (relative_path, content) to be written by the orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.core import get_jinja_env

__all__ = ["build_network_file_map", "build_networkd_outputs"]


def build_network_file_map(network_dir: Path) -> dict[str, Path]:
    """Build a map of network interface names to their drop-in directories.

    Scans *.network files in the network_dir and extracts the [Match] Name field,
    mapping it to the drop-in directory path for that interface.

    Args:
        network_dir: Directory containing .network files

    Returns:
        Dictionary mapping interface names to their drop-in directory paths
        Example: {"enp0s31f6": Path("/path/enp0s31f6.network.d"), ...}
    """
    network_files = {}

    for network_file in network_dir.glob("*.network"):
        # Read the file and extract Name from [Match] section
        content = network_file.read_text()
        iface_name = None

        in_match_section = False
        for line in content.splitlines():
            line = line.strip()

            if line == "[Match]":
                in_match_section = True
                continue
            elif line.startswith("["):
                in_match_section = False
                continue

            if in_match_section and line.startswith("Name="):
                iface_name = line.split("=", 1)[1].strip()
                break

        if iface_name:
            # Drop-in directory is <filename>.d
            dropin_dir = network_dir / f"{network_file.name}.d"
            network_files[iface_name] = dropin_dir

    return network_files


def build_networkd_outputs(
    hostname: str,
    ctx: dict[str, Any],
    host_templates: Path,
    shared_templates: Path,
) -> tuple[list[tuple[Path, str]], dict[str, Path]]:
    """Render networkd outputs for a host.

    Args:
        hostname: host name
        ctx: template context
        host_templates: path to host-specific templates
        shared_templates: path to shared templates

    Returns:
        (outputs, network_files)
        outputs: list of (relative_path, content) under systemd-networkd/
        network_files: map interface -> drop-in directory Path (based on rendered files)
    """
    env = get_jinja_env([host_templates, shared_templates])

    outputs: list[tuple[Path, str]] = []

    # Copy static .netdev files
    for netdev_file in host_templates.glob("*.netdev"):
        outputs.append((Path(netdev_file.name), netdev_file.read_text()))

    # Render .network.j2 templates
    for template_file in host_templates.glob("*.network.j2"):
        template_name = template_file.name
        output_name = template_name.replace(".j2", "")

        tpl = env.get_template(template_name)
        rendered = tpl.render(**ctx)
        outputs.append((Path(output_name), rendered))

    # Build network file map by inspecting rendered [Match] Name entries
    network_files: dict[str, Path] = {}
    for rel_path, content in outputs:
        if not rel_path.name.endswith(".network"):
            continue

        in_match = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "[Match]":
                in_match = True
                continue
            if stripped.startswith("[") and stripped != "[Match]":
                in_match = False
                continue
            if in_match and stripped.startswith("Name="):
                names = stripped.split("=", 1)[1].strip().split()
                for iface in names:
                    network_files[iface] = Path(f"{rel_path.name}.d")
                break

    return outputs, network_files
