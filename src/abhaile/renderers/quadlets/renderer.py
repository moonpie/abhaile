"""Quadlet rendering orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from abhaile.renderers.quadlets.container import (
    _render_service_quadlet_files,
    _resolve_container_definition,
)
from abhaile.renderers.quadlets.helpers import (
    _discover_build_image_files,
    _resolve_container_image_config,
    _resolve_managed_build_hints,
    _resolve_quadlet_source_file,
)
from abhaile.renderers.quadlets.network import (
    _lookup_service_vlan,
    _render_network_quadlets,
)
from abhaile.renderers.quadlets.pod import _render_pod_quadlets, _resolve_pod_definition
from abhaile.renderers.quadlets.volumes import (
    HostPathRegistry,
    _build_mounted_file_lines,
    _build_device_lines,
    _quadlet_output_root,
    _render_named_volumes,
    _validate_named_volumes,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError

LOG = logging.getLogger(__name__)


def render_service_quadlets(
    host: str,
    services: list[str],
    network: dict[str, Any],
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render quadlet files for container-based services."""
    if not services:
        return

    LOG.debug("render.quadlets host=%s count=%d", host, len(services))

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_output_dir = output_dir / "_shared"
    networks_output_dir = output_dir / "podman-networks"

    used_vlans: set[str] = set()
    host_paths_by_user: HostPathRegistry = {}

    for service in services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        podman = service_data.get("podman")
        if not podman:
            continue

        composition = service_data.get("composition", {})

        # Resolve pod/container from includes if not directly defined
        pod_def, _pod_source = _resolve_pod_definition(
            service=service,
            composition=composition,
            services_root=services_root,
        )

        container_def, _container_source = _resolve_container_definition(
            service=service,
            composition=composition,
            services_root=services_root,
        )

        if pod_def:
            _render_pod_quadlets(
                service=service,
                pod_def=pod_def,
                podman=podman,
                services_root=services_root,
                output_dir=output_dir,
                shared_output_dir=shared_output_dir,
                network=network,
                host=host,
                config_root=config_root,
                host_paths_by_user=host_paths_by_user,
                used_vlans=used_vlans,
                collector=collector,
                rendered_root=rendered_root,
            )
            continue

        if not container_def:
            raise RenderError(
                f"Podman service '{service}' must define or include composition.container "
                "or composition.pod"
            )

        user = podman.get("user")
        if not user:
            raise RenderError(f"Podman user missing for service '{service}'")

        quadlets_dir = services_root / service / "quadlets"

        named_volumes = container_def.get("named_volumes", []) or []
        if named_volumes:
            volume_template_path = (
                config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2"
            )
            if not volume_template_path.exists():
                raise RenderError(f"Missing volume template: {volume_template_path}")

        if named_volumes:
            _validate_named_volumes(service=service, container_def=container_def)

        container_template_path = _resolve_quadlet_source_file(
            service,
            services_root,
            "container.container.j2",
        )
        if container_template_path is None:
            if not quadlets_dir.exists():
                raise RenderError(f"Quadlets directory missing: {quadlets_dir}")
            raise RenderError(f"Missing container template for service '{service}'")

        output_root = _quadlet_output_root(user)
        output_root_relative = output_root.as_posix().lstrip("/")
        service_output_dir = output_dir / service / output_root_relative
        service_output_dir.mkdir(parents=True, exist_ok=True)

        build_path, image_path, build_filename, image_filename = _discover_build_image_files(
            quadlets_dir=quadlets_dir,
            service=service,
            services_root=services_root,
        )
        image_reference, pull_policy = _resolve_container_image_config(
            service=service,
            container_name=None,
            container_def=container_def,
            podman=podman,
            services_root=services_root,
        )
        if build_path is not None and image_reference is not None:
            raise RenderError(
                f"Service '{service}' specifies both registry image and local build sources"
            )
        build_apply_hints = (
            _resolve_managed_build_hints(service, services_root) if build_path is not None else None
        )

        volume_lines, volume_owner_refs = _render_named_volumes(
            service=service,
            container_def=container_def,
            user=user,
            output_root_relative=output_root_relative,
            output_dir=output_dir,
            shared_output_dir=shared_output_dir,
            host_paths_by_user=host_paths_by_user,
            config_root=config_root,
            name_prefix=f"{service}-",
            shared_volume_is_global=False,
            collector=collector,
            rendered_root=rendered_root,
        )
        volume_lines.extend(_build_mounted_file_lines(container_def))
        device_lines = _build_device_lines(container_def)

        container_owner_requires = list(volume_owner_refs)

        if podman.get("network") == "ipvlan-l2":
            vlan = _lookup_service_vlan(service, network)
            used_vlans.add(vlan)
            container_owner_requires.append(f"unit:{vlan}-network.service")

        if build_filename is not None:
            container_owner_requires.append(f"unit:{Path(build_filename).stem}-build.service")

        _render_service_quadlet_files(
            service=service,
            quadlets_dir=quadlets_dir,
            output_dir=service_output_dir,
            network=network,
            host=host,
            volume_lines=volume_lines,
            container_template_path=container_template_path,
            build_path=build_path,
            image_path=image_path,
            device_lines=device_lines,
            build_filename=build_filename,
            image_filename=image_filename,
            image_reference=image_reference,
            pull_policy=pull_policy,
            build_apply_hints=build_apply_hints,
            output_root=output_root,
            collector=collector,
            rendered_root=rendered_root,
            container_owner_requires=sorted(set(container_owner_requires)),
        )

    if used_vlans:
        _render_network_quadlets(
            host=host,
            network=network,
            vlans=sorted(used_vlans),
            output_dir=networks_output_dir,
            config_root=config_root,
            collector=collector,
            rendered_root=rendered_root,
        )
