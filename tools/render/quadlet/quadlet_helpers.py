"""Consolidated Quadlet helpers.

Provides template environment setup and volume rendering utilities shared
across container and pod quadlet rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment

from tools.common.core import get_jinja_env, get_logger, strip_cidr

logger = get_logger(__name__)


def quadlet_env(search_paths: Iterable[str]) -> Environment:
    """Construct a Jinja2 environment with shared quadlet filters.

    Args:
        search_paths: Iterable of template search paths.

    Returns:
        Environment: Configured Jinja2 environment with strip_cidr filter.
    """
    return get_jinja_env(search_paths, filters={"strip_cidr": strip_cidr})


def prefix_name(service: str, base: str) -> str:
    """Build a namespaced quadlet unit name.

    Args:
        service: Service name.
        base: Base unit name.

    Returns:
        str: Combined name in the form ``<service>.<base>``.
    """
    return f"{service}.{base}"


def build_volume_lines(
    container_meta: dict[str, Any],
    service_name: str,
    container_name: str | None = None,
    *,
    use_volume_units: bool = True,
) -> list[str]:
    """Build Volume= lines from container metadata.

    Always appends ``.volume`` suffix for named volumes (per Podman quadlet
    requirements). Only ``ro`` or ``rw`` are supported.

    Args:
        container_meta: Container metadata dictionary.
        service_name: Name of the owning service.
        container_name: Optional container name (for multi-container services).
        use_volume_units: Whether to reference generated volume units instead of host paths.

    Returns:
        list[str]: Volume lines suitable for quadlet unit files.
    """
    lines: list[str] = []

    # Named volumes
    for vol in container_meta.get("named_volumes", []):
        vol_name = vol.get("name")
        host_path = vol.get("host")
        mount_path = vol.get("mount")
        if not vol_name or not host_path or not mount_path:
            continue
        mode = vol.get("mode", "rw")

        if use_volume_units:
            if vol.get("shared", False):
                volume_unit = f"{vol_name}.volume"
            elif container_name:
                base_name = f"{service_name}-app-{container_name}-{vol_name}"
                volume_unit = f"{base_name}.volume"
            else:
                base_name = f"{service_name}-{vol_name}"
                volume_unit = f"{base_name}.volume"
            lines.append(f"Volume={volume_unit}:{mount_path}:{mode}")
        else:
            lines.append(f"Volume={host_path}:{mount_path}:{mode}")

    # Mounted files: direct host path references
    for mf in container_meta.get("mounted_files", []):
        host_path = mf.get("host")
        mount_path = mf.get("mount")
        if not host_path or not mount_path:
            continue
        mode = mf.get("mode", "rw")
        lines.append(f"Volume={host_path}:{mount_path}:{mode}")

    return lines


def render_volume_units(
    unit_prefix: str,
    container_meta: dict[str, Any],
    quadlet_dir: Path,
    out_dir: Path,
    shared_volumes_created: set,
    container_name: str | None = None,
    *,
    is_rootless: bool = False,
    rootless_user: str = "abhaile",
) -> None:
    """Render .volume units for named volumes.

    Shared volumes are emitted once per host under ``services/_shared`` to
    avoid duplication; non-shared volumes are emitted alongside the
    consuming service.

    Args:
        unit_prefix: Prefix for generated unit names.
        container_meta: Container metadata dictionary.
        quadlet_dir: Destination directory for generated quadlets.
        out_dir: Rendered output root.
        shared_volumes_created: Set tracking already-created shared volumes.
        container_name: Optional container name (for multi-container services).
        is_rootless: Whether rendering for rootless containers.
        rootless_user: Username for rootless container configs.
    """

    for vol in container_meta.get("named_volumes", []):
        vol_name = vol.get("name")
        if not vol_name:
            continue

        is_shared = vol.get("shared", False)

        if is_shared:
            shared_key = f"{vol_name}:{'rootless' if is_rootless else 'rootful'}"
            if shared_key in shared_volumes_created:
                continue

            if is_rootless:
                shared_dir = (
                    out_dir
                    / "services"
                    / "_shared"
                    / "home"
                    / rootless_user
                    / ".config"
                    / "containers"
                    / "systemd"
                )
            else:
                shared_dir = (
                    out_dir / "services" / "_shared" / "etc" / "containers" / "systemd"
                )

            shared_dir.mkdir(parents=True, exist_ok=True)
            vol_file = shared_dir / f"{vol_name}.volume"
            vol_file.write_text(f"[Volume]\nDevice={vol['host']}\nOptions=bind\n")
            logger.info("Wrote shared volume: %s", vol_file)
            shared_volumes_created.add(shared_key)
        else:
            if container_name:
                vol_unit_name = f"{unit_prefix}-app-{container_name}-{vol_name}.volume"
            else:
                vol_unit_name = f"{unit_prefix}-{vol_name}.volume"

            vol_file = quadlet_dir / vol_unit_name
            vol_file.write_text(f"[Volume]\nDevice={vol['host']}\nOptions=bind\n")
            logger.info("Wrote volume: %s", vol_file)


def build_volume_unit_outputs(
    unit_prefix: str,
    container_meta: dict[str, Any],
    quadlet_dir: Path,
    out_dir: Path,
    shared_volumes_created: set,
    container_name: str | None = None,
    *,
    is_rootless: bool = False,
    rootless_user: str = "abhaile",
) -> list[tuple[Path, str]]:
    """Build .volume unit outputs without writing to disk.

    Args:
        unit_prefix: Prefix for generated unit names.
        container_meta: Container metadata dictionary.
        quadlet_dir: Destination directory for generated quadlets.
        out_dir: Rendered output root.
        shared_volumes_created: Set tracking already-created shared volumes.
        container_name: Optional container name (for multi-container services).
        is_rootless: Whether rendering for rootless containers.
        rootless_user: Username for rootless container configs.

    Returns:
        list[tuple[Path, str]]: Destination path and file content pairs.
    """
    outputs: list[tuple[Path, str]] = []

    for vol in container_meta.get("named_volumes", []):
        vol_name = vol.get("name")
        if not vol_name:
            continue

        is_shared = vol.get("shared", False)

        content = f"[Volume]\nDevice={vol['host']}\nOptions=bind\n"

        if is_shared:
            shared_key = f"{vol_name}:{'rootless' if is_rootless else 'rootful'}"
            if shared_key in shared_volumes_created:
                continue

            if is_rootless:
                shared_dir = (
                    out_dir
                    / "services"
                    / "_shared"
                    / "home"
                    / rootless_user
                    / ".config"
                    / "containers"
                    / "systemd"
                )
            else:
                shared_dir = (
                    out_dir / "services" / "_shared" / "etc" / "containers" / "systemd"
                )

            outputs.append((shared_dir / f"{vol_name}.volume", content))
            shared_volumes_created.add(shared_key)
        else:
            if container_name:
                vol_unit_name = f"{unit_prefix}-app-{container_name}-{vol_name}.volume"
            else:
                vol_unit_name = f"{unit_prefix}-{vol_name}.volume"

            outputs.append((quadlet_dir / vol_unit_name, content))

    return outputs
