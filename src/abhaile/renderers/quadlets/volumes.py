"""Volume-related helpers for quadlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.quadlets.helpers import (
    _quadlet_kind_from_filename,
    _quadlet_unit_name,
    _register_quadlet_artifact,
    _validate_trailing_newline,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env

HostPathRegistry = dict[str, dict[str, tuple[str, bool]]]


def _register_host_path_usage(
    host_path: str,
    volume_filename: str,
    host_paths_by_user: HostPathRegistry,
    service: str,
    container_name: str | None,
    user: str,
    shared: bool,
) -> None:
    """Register host path usage and enforce shared-volume reuse rules."""
    user_registry = host_paths_by_user.setdefault(user, {})
    existing = user_registry.get(host_path)
    if existing is None:
        user_registry[host_path] = (volume_filename, shared)
        return

    existing_volume_filename, existing_shared = existing
    location = (
        f"service '{service}', container '{container_name}'"
        if container_name
        else f"service '{service}'"
    )

    if not shared or not existing_shared:
        raise RenderError(
            "Host path is mounted more than once for the same user and must be "
            "declared with shared=true for all uses: "
            f"{host_path} (user '{user}', {location})"
        )

    if volume_filename != existing_volume_filename:
        raise RenderError(
            "Host path is mounted more than once for the same user and must reuse "
            "the same shared volume name: "
            f"{host_path} (user '{user}', expected '{existing_volume_filename}', "
            f"got '{volume_filename}')"
        )


def _quadlet_output_root(user: str) -> Path:
    """Return the quadlet output root for the given user."""
    if user == "root":
        return Path("/etc/containers/systemd")
    return Path(f"/home/{user}/.config/containers/systemd")


def _render_named_volumes(
    *,
    service: str,
    container_def: dict[str, Any],
    user: str,
    output_root_relative: str,
    output_dir: Path,
    shared_output_dir: Path,
    host_paths_by_user: HostPathRegistry,
    config_root: Path,
    container_name: str | None = None,
    name_prefix: str | None = None,
    shared_volume_is_global: bool,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Render named volume quadlets and return container volume lines."""
    named_volumes = container_def.get("named_volumes", []) or []
    if not named_volumes:
        return ([], [])

    if name_prefix is None:
        if container_name:
            name_prefix = f"{service}-app-{container_name}-"
        else:
            name_prefix = f"{service}-"

    volume_lines: list[str] = []
    volume_owner_refs: list[str] = []
    volume_template_path = config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2"
    if not volume_template_path.exists():
        raise RenderError(f"Missing volume template: {volume_template_path}")
    _validate_trailing_newline(
        volume_template_path,
        context="quadlet volume template",
    )

    jinja_env = create_jinja_env(volume_template_path.parent)

    for volume in named_volumes:
        name = volume.get("name")
        host_path = volume.get("host_path")
        mount_path = volume.get("mount_path")
        if not name or not host_path or not mount_path:
            if container_name:
                raise RenderError(f"Invalid named volume entry: {volume}")
            raise RenderError(f"Invalid named volume for service '{service}': {volume}")

        shared = bool(volume.get("shared", False))
        volume_filename = f"{name}.volume" if shared else f"{name_prefix}{name}.volume"
        output_base = (shared_output_dir if shared else output_dir / service) / output_root_relative
        output_base.mkdir(parents=True, exist_ok=True)
        volume_file_path = output_base / volume_filename

        _register_host_path_usage(
            host_path=host_path,
            volume_filename=volume_filename,
            host_paths_by_user=host_paths_by_user,
            service=service,
            container_name=container_name,
            user=user,
            shared=shared,
        )

        if shared and shared_volume_is_global and volume_file_path.exists():
            volume_line = _format_volume_line(volume_filename, mount_path, volume.get("mode"))
            volume_lines.append(volume_line)
            volume_owner_refs.append(f"unit:{_quadlet_unit_name(volume_filename)}")
            continue

        template = jinja_env.get_template(volume_template_path.name)
        rendered_content = template.render(host_path=host_path)

        volume_file_path.write_text(
            rendered_content,
            encoding="utf-8",
            newline="\n",
        )
        if collector is not None and rendered_root is not None:
            vol_target_root = Path("/") / output_root_relative
            volume_hints: dict[str, Any] = {
                "rootless": user != "root",
                "shared": shared,
            }
            if user != "root":
                volume_hints["podman_user"] = user
            _register_quadlet_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=volume_file_path,
                target_path=str(vol_target_root / volume_filename),
                kind=_quadlet_kind_from_filename(volume_filename),
                owner_ref=f"unit:{_quadlet_unit_name(volume_filename)}",
                content=rendered_content,
                apply_hints=volume_hints,
                owner_apply_hints=volume_hints,
                replace=shared,
            )

        volume_line = _format_volume_line(volume_filename, mount_path, volume.get("mode"))
        volume_lines.append(volume_line)
        volume_owner_refs.append(f"unit:{_quadlet_unit_name(volume_filename)}")

    return (volume_lines, sorted(set(volume_owner_refs)))


def _build_mounted_file_lines(container_def: dict[str, Any]) -> list[str]:
    """Build Volume= lines for mounted files entries."""
    mounted_files = container_def.get("mounted_files", []) or []
    volume_lines: list[str] = []
    for mount in mounted_files:
        host_path = mount.get("host_path")
        mount_path = mount.get("mount_path")
        if not host_path or not mount_path:
            raise RenderError(f"Invalid mounted file entry: {mount}")
        mode = mount.get("mode")
        volume_lines.append(_format_volume_line(host_path, mount_path, mode))
    return volume_lines


def _format_volume_line(source: str, target: str, mode: str | None) -> str:
    """Format a quadlet Volume= line for the given mount."""
    suffix = f":{mode}" if mode else ""
    return f"Volume={source}:{target}{suffix}"
