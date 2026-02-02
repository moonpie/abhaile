"""Host configuration renderer for systemd units, resolved, etc."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from renderers.config import render_config_entries


def render_host_config(
    host: str,
    host_config: Dict[str, Any],
    common_config: Dict[str, Any],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render host configuration files (systemd units, resolved, etc).

    Processes composition.config entries EXCEPT those for systemd-networkd,
    which has its own renderer due to drop-in generation.

    Handles:
    - /etc/systemd/resolved.conf and /etc/systemd/resolved.conf.d/*
    - /etc/systemd/system/*.service, *.timer, *.path, etc.
    - Any other host configuration files

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
    # Jinja2 context for templates
    context = {
        "network": network,
        "host_name": host,
    }

    # Filter to exclude networkd entries (handled by separate renderer)
    def is_not_networkd(entry: Dict[str, Any]) -> bool:
        dest = entry.get("destination", "")
        return not dest.startswith("/etc/systemd/network/")

    # Process common first (implicit include)
    common_entries = common_config.get("composition", {}).get("config", [])
    non_networkd_common = [e for e in common_entries if is_not_networkd(e)]

    render_config_entries(
        non_networkd_common,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
    )

    # Process host-specific (overrides/adds to common)
    host_entries = host_config.get("composition", {}).get("config", [])
    non_networkd_host = [e for e in host_entries if is_not_networkd(e)]

    render_config_entries(
        non_networkd_host,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
    )
