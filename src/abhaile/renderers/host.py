"""Host configuration renderer for systemd units, resolved, etc."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.config import (
    annotate_systemd_entries_with_apply_hints,
    filter_config_entries_by_destination_prefix,
    render_config_entries,
    resolve_config_entry_variables,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.metadata import classify_systemd_artifact


def render_host_config(
    host: str,
    host_config: dict[str, Any],
    common_config: dict[str, Any],
    network: dict[str, Any],
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
    host_services: list[str] | None = None,
) -> None:
    """Render host configuration files and host-owned systemd artifacts.

    Processes composition.config entries EXCEPT those for systemd-networkd,
    which has its own renderer due to drop-in generation.

    Handles:
    - /etc/systemd/resolved.conf and /etc/systemd/resolved.conf.d/*
    - composition.systemd units and drop-ins
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
        "host_services": host_services or [],
    }

    # Process common first (implicit include)
    common_entries = common_config.get("composition", {}).get("config", [])
    non_networkd_common = filter_config_entries_by_destination_prefix(
        common_entries,
        "/etc/systemd/network/",
        include=False,
    )

    render_config_entries(
        non_networkd_common,
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
    non_networkd_host = filter_config_entries_by_destination_prefix(
        host_entries,
        "/etc/systemd/network/",
        include=False,
    )

    render_config_entries(
        non_networkd_host,
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
        collector=collector,
        rendered_root=rendered_root,
        default_owner_ref=f"host:{host}",
    )

    common_systemd_entries = resolve_config_entry_variables(
        common_config.get("composition", {}).get("systemd", []),
        network,
    )
    render_config_entries(
        annotate_systemd_entries_with_apply_hints(common_systemd_entries),
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
        collector=collector,
        rendered_root=rendered_root,
        default_owner_ref=f"host:{host}",
        classify_artifact=lambda destination, _owner_ref, _is_directory: classify_systemd_artifact(
            destination,
        ),
    )

    host_systemd_entries = resolve_config_entry_variables(
        host_config.get("composition", {}).get("systemd", []),
        network,
    )
    render_config_entries(
        annotate_systemd_entries_with_apply_hints(host_systemd_entries),
        config_root / "hosts",
        config_root / "hosts",
        output_dir,
        context,
        collector=collector,
        rendered_root=rendered_root,
        default_owner_ref=f"host:{host}",
        classify_artifact=lambda destination, _owner_ref, _is_directory: classify_systemd_artifact(
            destination,
        ),
    )
