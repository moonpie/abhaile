"""Quadlet renderer for podman container services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.config import read_yaml
from utils.errors import RenderError


def render_service_quadlets(
    host: str,
    services: List[str],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render quadlet files for container-based services.

    Args:
        host: Host name (e.g., phobos, deimos).
        services: Services mapped to the host.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_dir: Path to rendered services root (rendered/services).

    Raises:
        RenderError: If rendering fails or validation errors occur.
    """
    if not services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_output_dir = output_dir / "_shared"
    networks_output_dir = output_dir / "podman-networks"

    used_vlans: Set[str] = set()
    host_paths_by_user: Dict[str, Set[str]] = {}

    for service in sorted(services):
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        podman = service_data.get("podman")
        if not podman:
            continue

        composition = service_data.get("composition", {})

        # Resolve pod/container from includes if not directly defined
        pod_def, pod_source = _resolve_pod_definition(
            service=service,
            composition=composition,
            services_root=services_root,
            visited=set(),
            stack=[],
        )

        container_def, container_source = _resolve_container_definition(
            service=service,
            composition=composition,
            services_root=services_root,
            visited=set(),
            stack=[],
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
            )
            continue

        if not container_def:
            continue

        user = podman.get("user")
        if not user:
            raise RenderError(f"Podman user missing for service '{service}'")

        quadlets_dir = services_root / service / "quadlets"
        if not quadlets_dir.exists():
            raise RenderError(f"Quadlets directory missing: {quadlets_dir}")

        output_root = _quadlet_output_root(user)
        output_root_relative = output_root.as_posix().lstrip("/")
        service_output_dir = output_dir / service / output_root_relative
        service_output_dir.mkdir(parents=True, exist_ok=True)

        build_files = sorted(
            path
            for path in quadlets_dir.rglob("build.build")
            if path.parent == quadlets_dir
        )
        image_files = sorted(
            path
            for path in quadlets_dir.rglob("image.image")
            if path.parent == quadlets_dir
        )

        if len(build_files) > 1:
            raise RenderError(
                f"Multiple build.build files found for service '{service}'"
            )
        if len(image_files) > 1:
            raise RenderError(
                f"Multiple image.image files found for service '{service}'"
            )

        build_filename = f"{service}.build" if build_files else None
        image_filename = f"{service}.image" if image_files else None

        volume_lines = _render_named_volumes(
            service=service,
            container_def=container_def,
            user=user,
            output_root_relative=output_root_relative,
            output_dir=output_dir,
            shared_output_dir=shared_output_dir,
            host_paths_by_user=host_paths_by_user,
            config_root=config_root,
        )
        volume_lines.extend(_build_mounted_file_lines(container_def))

        if podman.get("network") == "ipvlan-l2":
            vlan = _lookup_service_vlan(service, network)
            used_vlans.add(vlan)

        _render_service_quadlet_files(
            service=service,
            quadlets_dir=quadlets_dir,
            output_dir=service_output_dir,
            network=network,
            host=host,
            volume_lines=volume_lines,
            build_filename=build_filename,
            image_filename=image_filename,
        )

    if used_vlans:
        _render_network_quadlets(
            host=host,
            network=network,
            vlans=sorted(used_vlans),
            output_dir=networks_output_dir,
            config_root=config_root,
        )


def _resolve_pod_definition(
    service: str,
    composition: Dict[str, Any],
    services_root: Path,
    visited: Set[str],
    stack: List[str],
) -> Tuple[Dict[str, Any] | None, str | None]:
    """Resolve pod definition, checking includes recursively.

    Args:
        service: Service name.
        composition: Service composition dict.
        services_root: Path to config/services directory.
        visited: Set of already-visited services.
        stack: Current include stack for cycle detection.

    Returns:
        Tuple of (pod_def, source_service) or (None, None) if not found.

    Raises:
        RenderError: If cycle detected.
    """
    if service in stack:
        cycle = " -> ".join(stack + [service])
        raise RenderError(f"Service include cycle detected: {cycle}")

    # Check direct definition first
    pod_def = composition.get("pod")
    if pod_def:
        return pod_def, service

    if service in visited:
        return None, None

    stack.append(service)

    # Check includes
    includes = composition.get("include", []) or []
    for included in includes:
        included_yaml = services_root / included / "service.yaml"
        if not included_yaml.exists():
            raise RenderError(f"Missing service definition: {included_yaml}")

        included_data = read_yaml(included_yaml) or {}
        included_composition = included_data.get("composition", {})

        result, source = _resolve_pod_definition(
            service=included,
            composition=included_composition,
            services_root=services_root,
            visited=visited,
            stack=stack,
        )
        if result:
            stack.pop()
            visited.add(service)
            return result, source

    stack.pop()
    visited.add(service)
    return None, None


def _resolve_container_definition(
    service: str,
    composition: Dict[str, Any],
    services_root: Path,
    visited: Set[str],
    stack: List[str],
) -> Tuple[Dict[str, Any] | None, str | None]:
    """Resolve container definition, checking includes recursively.

    Args:
        service: Service name.
        composition: Service composition dict.
        services_root: Path to config/services directory.
        visited: Set of already-visited services.
        stack: Current include stack for cycle detection.

    Returns:
        Tuple of (container_def, source_service) or (None, None) if not found.

    Raises:
        RenderError: If cycle detected.
    """
    if service in stack:
        cycle = " -> ".join(stack + [service])
        raise RenderError(f"Service include cycle detected: {cycle}")

    # Check direct definition first
    container_def = composition.get("container")
    if container_def:
        return container_def, service

    if service in visited:
        return None, None

    stack.append(service)

    # Check includes
    includes = composition.get("include", []) or []
    for included in includes:
        included_yaml = services_root / included / "service.yaml"
        if not included_yaml.exists():
            raise RenderError(f"Missing service definition: {included_yaml}")

        included_data = read_yaml(included_yaml) or {}
        included_composition = included_data.get("composition", {})

        result, source = _resolve_container_definition(
            service=included,
            composition=included_composition,
            services_root=services_root,
            visited=visited,
            stack=stack,
        )
        if result:
            stack.pop()
            visited.add(service)
            return result, source

    stack.pop()
    visited.add(service)
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
    host_paths_by_user: Dict[str, Set[str]],
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

    pod_name = f"{service}-app.pod"

    jinja_env = Environment(
        loader=FileSystemLoader(quadlets_dir),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

    pod_template = jinja_env.get_template("pod.pod.j2")
    pod_rendered = pod_template.render(
        network=network,
        host_name=host,
        service_name=service,
    )
    (service_output_dir / pod_name).write_text(pod_rendered)

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
        volume_lines = _render_named_volumes_for_pod_container(
            service=service,
            container_name=container_name,
            container_def=container_def,
            user=user,
            output_root_relative=output_root_relative,
            output_dir=output_dir,
            shared_output_dir=shared_output_dir,
            host_paths_by_user=host_paths_by_user,
            config_root=config_root,
        )
        volume_lines.extend(_build_mounted_file_lines(container_def))

        # Find build and image files for this container
        build_files = sorted(
            path
            for path in container_dir.rglob("build.build")
            if path.parent == container_dir
        )
        image_files = sorted(
            path
            for path in container_dir.rglob("image.image")
            if path.parent == container_dir
        )

        if len(build_files) > 1:
            raise RenderError(
                f"Multiple build.build files found for container '{container_name}' in pod service '{service}'"
            )
        if len(image_files) > 1:
            raise RenderError(
                f"Multiple image.image files found for container '{container_name}' in pod service '{service}'"
            )

        build_filename = (
            f"{service}-app-{container_name}.build" if build_files else None
        )
        image_filename = (
            f"{service}-app-{container_name}.image" if image_files else None
        )

        # Render container quadlet template
        container_template_path = container_dir / "container.container.j2"
        if not container_template_path.exists():
            raise RenderError(f"Missing container template: {container_template_path}")

        jinja_env_container = Environment(
            loader=FileSystemLoader(container_dir),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        jinja_env_container.filters["strip_cidr"] = _strip_cidr

        template_text = container_template_path.read_text()
        if "{{ image" in template_text and not image_filename:
            raise RenderError(
                f"Template expects image but image.image not found: {container_template_path}"
            )
        if "{{ build" in template_text and not build_filename:
            raise RenderError(
                f"Template expects build but build.build not found: {container_template_path}"
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
        (service_output_dir / container_output_name).write_text(container_rendered)

        # Copy build and image files
        if build_files:
            target = service_output_dir / build_filename
            target.write_text(build_files[0].read_text())

        if image_files:
            target = service_output_dir / image_filename
            target.write_text(image_files[0].read_text())


def _render_named_volumes_for_pod_container(
    service: str,
    container_name: str,
    container_def: Dict[str, Any],
    user: str,
    output_root_relative: str,
    output_dir: Path,
    shared_output_dir: Path,
    host_paths_by_user: Dict[str, Set[str]],
    config_root: Path,
) -> List[str]:
    """Render named volumes for a container in a pod.

    Similar to _render_named_volumes but prefixes volume names with service-app-container.

    Args:
        service: Service name.
        container_name: Container name within the pod.
        container_def: Container definition with named_volumes.
        user: User (root or username).
        output_root_relative: Relative path to output root.
        output_dir: Base output directory.
        shared_output_dir: Shared output directory.
        host_paths_by_user: Tracking dict for host path validation.
        config_root: Path to config/ directory.

    Returns:
        List of volume lines for the container quadlet.

    Raises:
        RenderError: If validation fails.
    """
    named_volumes = container_def.get("named_volumes", []) or []
    if not named_volumes:
        return []

    volume_lines: List[str] = []
    volume_template_path = (
        config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2"
    )
    if not volume_template_path.exists():
        raise RenderError(f"Missing volume template: {volume_template_path}")

    jinja_env = Environment(
        loader=FileSystemLoader(volume_template_path.parent),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    for volume in named_volumes:
        name = volume.get("name")
        host_path = volume.get("host_path")
        mount_path = volume.get("mount_path")
        if not name or not host_path or not mount_path:
            raise RenderError(f"Invalid named volume entry: {volume}")

        shared = volume.get("shared", False)

        if shared:
            # Shared volumes go to _shared/ directory and use unprefixed names
            volume_filename = f"{name}.volume"
            output_base = shared_output_dir / output_root_relative
        else:
            # Non-shared volumes are prefixed with service-app-container
            volume_filename = f"{service}-app-{container_name}-{name}.volume"
            output_base = output_dir / service / output_root_relative

        # Track host paths for duplicate detection (skip for shared volumes that already exist)
        output_base.mkdir(parents=True, exist_ok=True)
        volume_file_path = output_base / volume_filename

        if shared and volume_file_path.exists():
            # Shared volume already rendered by another container, just add the volume line
            volume_line = _format_volume_line(
                volume_filename, mount_path, volume.get("mode")
            )
            volume_lines.append(volume_line)
            continue

        if user not in host_paths_by_user:
            host_paths_by_user[user] = set()

        if host_path in host_paths_by_user[user]:
            raise RenderError(
                f"Duplicate host_path '{host_path}' found for user '{user}'"
            )
        host_paths_by_user[user].add(host_path)

        template = jinja_env.get_template(volume_template_path.name)
        rendered_content = template.render(host_path=host_path)

        volume_file_path.write_text(rendered_content)

        volume_line = _format_volume_line(
            volume_filename, mount_path, volume.get("mode")
        )
        volume_lines.append(volume_line)

    return volume_lines


def _quadlet_output_root(user: str) -> Path:
    if user == "root":
        return Path("/etc/containers/systemd")
    return Path(f"/home/{user}/.config/containers/systemd")


def _render_named_volumes(
    service: str,
    container_def: Dict[str, Any],
    user: str,
    output_root_relative: str,
    output_dir: Path,
    shared_output_dir: Path,
    host_paths_by_user: Dict[str, Set[str]],
    config_root: Path,
) -> List[str]:
    named_volumes = container_def.get("named_volumes", []) or []
    if not named_volumes:
        return []

    volume_lines: List[str] = []
    volume_template_path = (
        config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2"
    )
    if not volume_template_path.exists():
        raise RenderError(f"Missing volume template: {volume_template_path}")

    jinja_env = Environment(
        loader=FileSystemLoader(volume_template_path.parent),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    for volume in named_volumes:
        name = volume.get("name")
        host_path = volume.get("host_path")
        mount_path = volume.get("mount_path")
        if not name or not host_path or not mount_path:
            raise RenderError(f"Invalid named volume for service '{service}': {volume}")

        shared = bool(volume.get("shared", False))
        if not shared:
            existing = host_paths_by_user.setdefault(user, set())
            if host_path in existing:
                raise RenderError(
                    "Host path rendered more than once without shared=true: "
                    f"{host_path} (service '{service}', user '{user}')"
                )
            existing.add(host_path)

        volume_filename = f"{name}.volume" if shared else f"{service}-{name}.volume"
        output_base = (
            shared_output_dir if shared else output_dir / service
        ) / output_root_relative
        output_base.mkdir(parents=True, exist_ok=True)

        template = jinja_env.get_template(volume_template_path.name)
        rendered_content = template.render(host_path=host_path)

        (output_base / volume_filename).write_text(rendered_content)

        volume_line = _format_volume_line(
            volume_filename, mount_path, volume.get("mode")
        )
        volume_lines.append(volume_line)

    return volume_lines


def _build_mounted_file_lines(container_def: Dict[str, Any]) -> List[str]:
    mounted_files = container_def.get("mounted_files", []) or []
    volume_lines: List[str] = []
    for mount in mounted_files:
        host_path = mount.get("host_path")
        mount_path = mount.get("mount_path")
        if not host_path or not mount_path:
            raise RenderError(f"Invalid mounted file entry: {mount}")
        volume_lines.append(
            _format_volume_line(host_path, mount_path, mount.get("mode"))
        )
    return volume_lines


def _format_volume_line(source: str, target: str, mode: str | None) -> str:
    suffix = f":{mode}" if mode else ""
    return f"Volume={source}:{target}{suffix}"


def _render_service_quadlet_files(
    service: str,
    quadlets_dir: Path,
    output_dir: Path,
    network: Dict[str, Any],
    host: str,
    volume_lines: List[str],
    build_filename: str | None,
    image_filename: str | None,
) -> None:
    jinja_env = Environment(
        loader=FileSystemLoader(quadlets_dir),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

    for source_path in sorted(quadlets_dir.rglob("*")):
        if source_path.is_dir():
            continue
        if source_path.parent != quadlets_dir:
            # Only render files at the service quadlets root for container services
            continue

        if source_path.suffix == ".j2":
            if source_path.name != "container.container.j2":
                raise RenderError(f"Unsupported quadlet template: {source_path}")

            template_text = source_path.read_text()
            if "{{ image" in template_text and not image_filename:
                raise RenderError(
                    f"Template expects image but image.image not found: {source_path}"
                )
            if "{{ build" in template_text and not build_filename:
                raise RenderError(
                    f"Template expects build but build.build not found: {source_path}"
                )

            template = jinja_env.get_template(source_path.name)
            rendered = template.render(
                network=network,
                host_name=host,
                service_name=service,
                volume_lines=volume_lines,
                image=image_filename,
                build=build_filename,
            )
            (output_dir / f"{service}.container").write_text(rendered)
            continue

        if source_path.name == "image.image":
            target = output_dir / f"{service}.image"
            target.write_text(source_path.read_text())
            continue

        if source_path.name == "build.build":
            target = output_dir / f"{service}.build"
            target.write_text(source_path.read_text())
            continue

        # Copy any other static quadlet files as-is
        target = output_dir / source_path.name
        target.write_text(source_path.read_text())


def _lookup_service_vlan(service: str, network: Dict[str, Any]) -> str:
    service_def = network.get("services", {}).get(service)
    if not service_def:
        raise RenderError(f"Missing network.services entry for service '{service}'")
    vlan = service_def.get("vlan")
    if not vlan:
        raise RenderError(f"Missing VLAN for service '{service}'")
    return vlan


def _render_network_quadlets(
    host: str,
    network: Dict[str, Any],
    vlans: List[str],
    output_dir: Path,
    config_root: Path,
) -> None:
    template_path = (
        config_root / "_templates" / "services" / "quadlets" / "network.network.j2"
    )
    if not template_path.exists():
        raise RenderError(f"Missing network template: {template_path}")

    output_root = Path("/etc/containers/systemd")
    output_root_relative = output_root.as_posix().lstrip("/")
    output_base = output_dir / output_root_relative
    output_base.mkdir(parents=True, exist_ok=True)

    jinja_env = Environment(
        loader=FileSystemLoader(template_path.parent),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

    template = jinja_env.get_template(template_path.name)

    for vlan_name in vlans:
        rendered = template.render(
            network=network,
            host_name=host,
            vlan_name=vlan_name,
        )
        (output_base / f"{vlan_name}.network").write_text(rendered)


def _strip_cidr(address: str) -> str:
    return address.split("/")[0] if "/" in address else address
