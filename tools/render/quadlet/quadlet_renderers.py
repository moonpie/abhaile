"""Quadlet renderers for container and pod services.

Includes pure builders that return outputs and wrappers that write them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.core import get_logger

from .quadlet_helpers import (
    build_volume_lines,
    build_volume_unit_outputs,
    quadlet_env,
)

logger = get_logger(__name__)

__all__ = [
    "build_container_service_outputs",
    "render_container_service",
    "build_pod_service_outputs",
    "render_pod_service",
]


def build_container_service_outputs(
    svc: str,
    svc_meta: dict[str, Any],
    network: dict[str, Any],
    out_dir: Path,
    hostname: str,
    shared_volumes_created: set,
    root: Path,
    *,
    host_has_rootful_services: bool = False,
) -> list[tuple[Path, str]]:
    """Build quadlet outputs for a regular container service without writing."""
    mode = svc_meta.get("mode", "rootful")
    is_rootless = mode == "rootless"
    rootless_user = svc_meta.get("rootless_user", "abhaile")

    if is_rootless:
        quadlet_dir = (
            out_dir
            / "services"
            / svc
            / "home"
            / rootless_user
            / ".config"
            / "containers"
            / "systemd"
        )
    else:
        quadlet_dir = out_dir / "services" / svc / "etc" / "containers" / "systemd"

    svc_quadlet_dir = root / "config" / "services" / svc / "quadlets"
    if not svc_quadlet_dir.exists():
        return []

    build_image_tag = None
    outputs: list[tuple[Path, str]] = []

    for quadlet_file in svc_quadlet_dir.glob("*.build"):
        content = quadlet_file.read_text()
        dest = quadlet_dir / f"{svc}.build"
        outputs.append((dest, content))
        for line in content.splitlines():
            if line.startswith("ImageTag="):
                build_image_tag = line.split("=", 1)[1].strip()

    for quadlet_file in svc_quadlet_dir.glob("*.image"):
        content = quadlet_file.read_text()
        dest = quadlet_dir / f"{svc}.image"
        outputs.append((dest, content))

    for quadlet_file in svc_quadlet_dir.glob("*.network"):
        content = quadlet_file.read_text()
        dest = quadlet_dir / f"{svc}.network"
        outputs.append((dest, content))

    container_meta = svc_meta.get("container", {})
    outputs.extend(
        build_volume_unit_outputs(
            svc,
            container_meta,
            quadlet_dir,
            out_dir,
            shared_volumes_created,
            is_rootless=is_rootless,
            rootless_user=rootless_user,
        )
    )

    for template_file in svc_quadlet_dir.glob("*.container.j2"):
        env = quadlet_env([svc_quadlet_dir])

        managed_volume_lines = build_volume_lines(
            container_meta,
            svc,
            use_volume_units=True,
        )
        managed_image_ref = f"{svc}.build" if build_image_tag else f"{svc}.image"
        managed_ctx = {
            "service": svc_meta,
            "service_name": svc,
            "network": network,
            "services": network.get("services", {}),
            "hostname": hostname,
            "image": managed_image_ref,
            "build": managed_image_ref,
            "volume_lines": managed_volume_lines,
        }
        tpl = env.get_template(template_file.name)
        managed_rendered = tpl.render(**managed_ctx)
        dest = quadlet_dir / f"{svc}.container"
        outputs.append((dest, managed_rendered))

    return outputs


def render_container_service(
    svc: str,
    svc_meta: dict[str, Any],
    network: dict[str, Any],
    out_dir: Path,
    hostname: str,
    shared_volumes_created: set,
    root: Path,
    *,
    host_has_rootful_services: bool = False,
) -> None:
    """Render quadlets for a regular container service (writes to disk)."""
    outputs = build_container_service_outputs(
        svc,
        svc_meta,
        network,
        out_dir,
        hostname,
        shared_volumes_created,
        root,
        host_has_rootful_services=host_has_rootful_services,
    )
    for dest, content in outputs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
        logger.info("Wrote quadlet: %s", dest)


def build_pod_service_outputs(
    svc: str,
    svc_meta: dict[str, Any],
    network: dict[str, Any],
    out_dir: Path,
    hostname: str,
    shared_volumes_created: set,
    root: Path,
    *,
    host_has_rootful_services: bool = False,
) -> list[tuple[Path, str]]:
    """Build quadlet outputs for a pod service without writing."""
    mode = svc_meta.get("mode", "rootful")
    is_rootless = mode == "rootless"
    rootless_user = svc_meta.get("rootless_user", "abhaile")

    if is_rootless:
        quadlet_dir = (
            out_dir
            / "services"
            / svc
            / "home"
            / rootless_user
            / ".config"
            / "containers"
            / "systemd"
        )
    else:
        quadlet_dir = out_dir / "services" / svc / "etc" / "containers" / "systemd"

    svc_quadlet_dir = root / "config" / "services" / svc / "quadlets"
    if not svc_quadlet_dir.exists():
        return []

    pod_name = f"{svc}-app"
    outputs: list[tuple[Path, str]] = []

    pod_template = svc_quadlet_dir / "pod.pod.j2"
    if pod_template.exists():
        env = quadlet_env([svc_quadlet_dir])
        tpl = env.get_template("pod.pod.j2")
        ctx = {
            "service": svc_meta,
            "service_name": svc,
            "network": network,
            "services": network.get("services", {}),
            "hostname": hostname,
        }
        rendered = tpl.render(**ctx)
        dest = quadlet_dir / f"{pod_name}.pod"
        outputs.append((dest, rendered))

    pod_meta = svc_meta.get("pod", {})
    containers = pod_meta.get("containers", [])

    for container_def in containers:
        container_name = container_def.get("name")
        if not container_name:
            continue

        container_quadlet_dir = svc_quadlet_dir / container_name
        if not container_quadlet_dir.exists():
            continue

        for img_file in container_quadlet_dir.glob("*.image"):
            dest = quadlet_dir / f"{pod_name}-{container_name}.image"
            outputs.append((dest, img_file.read_text()))

        outputs.extend(
            build_volume_unit_outputs(
                svc,
                container_def,
                quadlet_dir,
                out_dir,
                shared_volumes_created,
                container_name=container_name,
                is_rootless=is_rootless,
                rootless_user=rootless_user,
            )
        )

        for template_file in container_quadlet_dir.glob("*.container.j2"):
            env = quadlet_env([container_quadlet_dir])
            volume_lines = build_volume_lines(
                container_def,
                svc,
                container_name,
            )

            image_ref = f"{pod_name}-{container_name}.image"
            tpl = env.get_template(template_file.name)
            ctx = {
                "service": svc_meta,
                "service_name": svc,
                "network": network,
                "services": network.get("services", {}),
                "hostname": hostname,
                "pod": f"{pod_name}.pod",
                "image": image_ref,
                "build": image_ref,
                "volume_lines": volume_lines,
            }
            rendered = tpl.render(**ctx)
            dest = quadlet_dir / f"{pod_name}-{container_name}.container"
            outputs.append((dest, rendered))

    return outputs


def render_pod_service(
    svc: str,
    svc_meta: dict[str, Any],
    network: dict[str, Any],
    out_dir: Path,
    hostname: str,
    shared_volumes_created: set,
    root: Path,
    *,
    host_has_rootful_services: bool = False,
) -> None:
    """Render quadlets for a pod service (writes to disk)."""
    outputs = build_pod_service_outputs(
        svc,
        svc_meta,
        network,
        out_dir,
        hostname,
        shared_volumes_created,
        root,
        host_has_rootful_services=host_has_rootful_services,
    )
    for dest, content in outputs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
        logger.info("Wrote quadlet: %s", dest)
