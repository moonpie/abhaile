"""Podman quadlet rendering for container and pod services.

Provides a pure builder returning outputs and a wrapper that writes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .quadlet_renderers import (
    build_container_service_outputs,
    build_pod_service_outputs,
)


def build_quadlet_outputs(
    hostname: str,
    host_services: list[str],
    network: dict[str, Any],
    services_meta: dict[str, Any],
    out_dir: Path,
    root: Path | None = None,
) -> list[tuple[Path, str]]:
    """Build Podman quadlet outputs for container and pod services.

    Returns a list of (destination_path, content) tuples including
    .container, .network, .volume, .image, .build, and .pod quadlet files
    based on service definitions. Handles both regular containers and pods.

    Args:
        hostname: Target hostname.
        host_services: List of services deployed on this host.
        network: Network configuration.
        services_meta: Service metadata dictionary.
        out_dir: Output directory for quadlets.
        root: Repository root (defaults to module location).

    Returns:
        list[tuple[Path, str]]: Destination path and file content pairs.
    """
    if root is None:
        root = Path(__file__).resolve().parents[4]

    # Check if host has any rootful container/pod services
    host_has_rootful_services = any(
        services_meta.get(svc, {}).get("mode", "rootful") == "rootful"
        for svc in host_services
        if services_meta.get(svc, {}).get("type") in ["container", "pod"]
    )

    # Track shared volumes across all services to ensure single creation
    shared_volumes_created: set[str] = set()

    outputs: list[tuple[Path, str]] = []

    for svc in host_services:
        svc_meta = services_meta.get(svc, {})
        svc_type = svc_meta.get("type")

        # Handle both "container" and "pod" types
        if svc_type == "container":
            outputs.extend(
                build_container_service_outputs(
                    svc,
                    svc_meta,
                    network,
                    out_dir,
                    hostname,
                    shared_volumes_created,
                    root,
                    host_has_rootful_services=host_has_rootful_services,
                )
            )
        elif svc_type == "pod":
            outputs.extend(
                build_pod_service_outputs(
                    svc,
                    svc_meta,
                    network,
                    out_dir,
                    hostname,
                    shared_volumes_created,
                    root,
                    host_has_rootful_services=host_has_rootful_services,
                )
            )

    return outputs


def render_quadlets(
    hostname: str,
    host_services: list[str],
    network: dict[str, Any],
    services_meta: dict[str, Any],
    out_dir: Path,
    root: Path | None = None,
) -> None:
    """Render Podman quadlet files for container services (writes to disk).

    Args:
        hostname: Target hostname.
        host_services: List of services deployed on this host.
        network: Network configuration.
        services_meta: Service metadata dictionary.
        out_dir: Output directory for quadlets.
        root: Repository root (defaults to module location).
    """
    outputs = build_quadlet_outputs(
        hostname=hostname,
        host_services=host_services,
        network=network,
        services_meta=services_meta,
        out_dir=out_dir,
        root=root,
    )
    for dest, content in outputs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
