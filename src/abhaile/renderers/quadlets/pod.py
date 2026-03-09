"""Pod-specific quadlet rendering helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set, Tuple

from abhaile.renderers.quadlets.container import _validate_template_variables
from abhaile.renderers.quadlets.helpers import _validate_trailing_newline
from abhaile.renderers.quadlets.helpers import _discover_build_image_files
from abhaile.renderers.quadlets.network import _lookup_service_vlan
from abhaile.renderers.quadlets.volumes import (
    HostPathRegistry,
    _build_mounted_file_lines,
    _quadlet_output_root,
    _render_named_volumes,
)
from abhaile.utils.composition import resolve_composition
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def _resolve_pod_definition(
    service: str,
    composition: Dict[str, Any],
    services_root: Path,
) -> Tuple[Dict[str, Any] | None, str | None]:
    """Resolve pod definition, checking includes recursively.

    Args:
        service: Service name.
        composition: Service composition dict.
        services_root: Path to config/services directory.
    Returns:
        Tuple of (pod_def, source_service) or (None, None) if not found.
    """
    # Check direct definition first
    pod_def = composition.get("pod")
    if pod_def:
        return pod_def, service

    config_root = services_root.parent
    includes = composition.get("include", []) or []
    for included in includes:
        included_composition = resolve_composition(
            service_name=included,
            config_root=config_root,
            merge_strategy="deep",
        )
        pod_def = included_composition.get("pod")
        if pod_def:
            return pod_def, included

    return None, None


def _render_pod_quadlets(
    service: str,
    pod_def: Dict[str, Any],
    podman: Dict[str, Any],
    services_root: Path,
    output_dir: Path,
    shared_output_dir: Path,
    network: Dict[str, Any],
    host: str,
    config_root: Path,
    host_paths_by_user: HostPathRegistry,
    used_vlans: Set[str],
) -> None:
    """Render quadlet files for a pod service.

    Args:
        service: Service name.
        pod_def: Pod definition from composition.pod.
        podman: Podman configuration.
        services_root: Path to config/services directory.
        output_dir: Path to rendered services root.
        shared_output_dir: Path to shared output directory.
        network: Network configuration from network.yaml.
        host: Host name.
        config_root: Path to config/ directory.
        host_paths_by_user: Tracking dict for host path validation.
        used_vlans: Set to track used VLANs.

    Raises:
        RenderError: If rendering fails.
    """
    user = podman.get("user")
    if not user:
        raise RenderError(f"Podman user missing for pod service '{service}'")

    quadlets_dir = services_root / service / "quadlets"
    if not quadlets_dir.exists():
        raise RenderError(f"Quadlets directory missing: {quadlets_dir}")

    output_root = _quadlet_output_root(user)
    output_root_relative = output_root.as_posix().lstrip("/")
    service_output_dir = output_dir / service / output_root_relative
    service_output_dir.mkdir(parents=True, exist_ok=True)

    # Render pod quadlet
    pod_template_path = quadlets_dir / "pod.pod.j2"
    if not pod_template_path.exists():
        raise RenderError(f"Missing pod template: {pod_template_path}")
    _validate_trailing_newline(
        pod_template_path,
        context="quadlet pod template",
    )

    pod_name = f"{service}-app.pod"

    jinja_env = create_jinja_env(quadlets_dir)

    pod_template = jinja_env.get_template("pod.pod.j2")
    pod_rendered = pod_template.render(
        network=network,
        host_name=host,
        service_name=service,
    )
    (service_output_dir / pod_name).write_text(
        pod_rendered,
        encoding="utf-8",
        newline="\n",
    )

    # Track VLAN for network quadlet generation
    if podman.get("network") == "ipvlan-l2":
        vlan = _lookup_service_vlan(service, network)
        used_vlans.add(vlan)

    # Render containers in the pod
    containers = pod_def.get("containers", []) or []
    if not containers:
        raise RenderError(f"Pod service '{service}' has no containers")

    for container in containers:
        container_name = container.get("name")
        if not container_name:
            raise RenderError(f"Container missing 'name' in pod service '{service}'")

        # Extract container definition (may be under 'container' key or directly in container dict)
        container_def = container.get("container", container)

        container_dir = quadlets_dir / container_name
        if not container_dir.exists():
            raise RenderError(
                f"Container directory missing: {container_dir} for pod service '{service}'"
            )

        # Render volumes for this container
        volume_lines = _render_named_volumes(
            service=service,
            container_name=container_name,
            container_def=container_def,
            user=user,
            output_root_relative=output_root_relative,
            output_dir=output_dir,
            shared_output_dir=shared_output_dir,
            host_paths_by_user=host_paths_by_user,
            config_root=config_root,
            name_prefix=f"{service}-app-{container_name}-",
            shared_volume_is_global=True,
        )
        volume_lines.extend(_build_mounted_file_lines(container_def))

        # Find build and image files for this container
        build_path, image_path, build_filename, image_filename = _discover_build_image_files(
            quadlets_dir=container_dir,
            service=service,
            container_name=container_name,
        )

        # Render container quadlet template
        container_template_path = container_dir / "container.container.j2"
        if not container_template_path.exists():
            raise RenderError(f"Missing container template: {container_template_path}")
        _validate_trailing_newline(
            container_template_path,
            context="quadlet container template",
        )

        jinja_env_container = create_jinja_env(container_dir)

        template_text = container_template_path.read_text(encoding="utf-8")

        # Use robust validation instead of string-contains checks
        _validate_template_variables("container.container.j2", template_text)

        # Check for conditional requirements
        if "{{ image" in template_text and not image_filename:
            raise RenderError(
                f"Template requires image variable but image.image not found: {container_template_path}"
            )
        if "{{ build" in template_text and not build_filename:
            raise RenderError(
                f"Template requires build variable but build.build not found: {container_template_path}"
            )

        container_template = jinja_env_container.get_template("container.container.j2")
        container_rendered = container_template.render(
            network=network,
            host_name=host,
            service_name=service,
            volume_lines=volume_lines,
            image=image_filename,
            build=build_filename,
            pod=pod_name,
        )
        container_output_name = f"{service}-app-{container_name}.container"
        (service_output_dir / container_output_name).write_text(
            container_rendered,
            encoding="utf-8",
            newline="\n",
        )

        # Copy build and image files
        if build_path:
            assert build_filename is not None
            _validate_trailing_newline(
                build_path,
                context="quadlet build source file",
            )
            target = service_output_dir / build_filename
            content = build_path.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8", newline="\n")

        if image_path:
            assert image_filename is not None
            _validate_trailing_newline(
                image_path,
                context="quadlet image source file",
            )
            target = service_output_dir / image_filename
            content = image_path.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8", newline="\n")
