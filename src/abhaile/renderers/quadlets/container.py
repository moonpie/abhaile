"""Container quadlet rendering helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.quadlets.helpers import (
    _quadlet_kind_from_filename,
    _quadlet_unit_name,
    _register_quadlet_artifact,
    _resolve_composition_definition,
    _validate_trailing_newline,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def _resolve_container_definition(
    service: str,
    composition: dict[str, Any],
    services_root: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve container definition, checking includes recursively."""
    return _resolve_composition_definition("container", service, composition, services_root)


def _render_service_quadlet_files(
    service: str,
    quadlets_dir: Path,
    output_dir: Path,
    network: dict[str, Any],
    host: str,
    volume_lines: list[str],
    build_filename: str | None,
    image_filename: str | None,
    *,
    output_root: Path | None = None,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
    container_owner_requires: list[str] | None = None,
) -> None:
    """Render container quadlet files for a service into the output directory."""
    jinja_env = create_jinja_env(quadlets_dir)
    is_rootless = bool(output_root and not output_root.as_posix().startswith("/etc"))
    apply_hints: dict[str, Any] = {"rootless": is_rootless}
    if is_rootless and output_root is not None:
        output_root_parts = output_root.as_posix().split("/")
        if len(output_root_parts) > 2:
            apply_hints["podman_user"] = output_root_parts[2]

    for source_path in sorted(quadlets_dir.rglob("*")):
        if source_path.is_dir():
            continue
        if source_path.parent != quadlets_dir:
            # Only render files at the service quadlets root for container services
            continue

        _validate_trailing_newline(
            source_path,
            context="quadlet source file",
        )

        if source_path.suffix == ".j2":
            if source_path.name != "container.container.j2":
                raise RenderError(f"Unsupported quadlet template: {source_path}")

            template_text = source_path.read_text(encoding="utf-8")

            # Check for conditional requirements
            if "{{ image" in template_text and not image_filename:
                raise RenderError(
                    f"Template requires image variable but image.image not found: {source_path}"
                )
            if "{{ build" in template_text and not build_filename:
                raise RenderError(
                    f"Template requires build variable but build.build not found: {source_path}"
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
            container_filename = f"{service}.container"
            container_path = output_dir / container_filename
            container_path.write_text(rendered, encoding="utf-8", newline="\n")
            if collector is not None and rendered_root is not None and output_root is not None:
                _register_quadlet_artifact(
                    collector=collector,
                    rendered_root=rendered_root,
                    output_path=container_path,
                    target_path=str(output_root / container_filename),
                    kind=_quadlet_kind_from_filename(container_filename),
                    owner_ref=f"unit:{_quadlet_unit_name(container_filename)}",
                    content=rendered,
                    apply_hints=apply_hints,
                    owner_apply_hints=apply_hints,
                    owner_requires=container_owner_requires,
                )
            continue

        if source_path.name == "image.image":
            image_out_name = f"{service}.image"
            target = output_dir / image_out_name
            content = source_path.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8", newline="\n")
            if collector is not None and rendered_root is not None and output_root is not None:
                _register_quadlet_artifact(
                    collector=collector,
                    rendered_root=rendered_root,
                    output_path=target,
                    target_path=str(output_root / image_out_name),
                    kind=_quadlet_kind_from_filename(image_out_name),
                    owner_ref=f"unit:{_quadlet_unit_name(image_out_name)}",
                    content=content,
                    apply_hints=apply_hints,
                    owner_apply_hints=apply_hints,
                )
            continue

        if source_path.name == "build.build":
            build_out_name = f"{service}.build"
            target = output_dir / build_out_name
            content = source_path.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8", newline="\n")
            if collector is not None and rendered_root is not None and output_root is not None:
                _register_quadlet_artifact(
                    collector=collector,
                    rendered_root=rendered_root,
                    output_path=target,
                    target_path=str(output_root / build_out_name),
                    kind=_quadlet_kind_from_filename(build_out_name),
                    owner_ref=f"unit:{_quadlet_unit_name(build_out_name)}",
                    content=content,
                    apply_hints=apply_hints,
                    owner_apply_hints=apply_hints,
                )
            continue

        # Copy any other static quadlet files as-is
        target = output_dir / source_path.name
        content = source_path.read_text(encoding="utf-8")
        target.write_text(content, encoding="utf-8", newline="\n")
        if collector is not None and rendered_root is not None and output_root is not None:
            out_name = source_path.name
            _register_quadlet_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=target,
                target_path=str(output_root / out_name),
                kind=_quadlet_kind_from_filename(out_name),
                owner_ref=f"unit:{_quadlet_unit_name(out_name)}",
                content=content,
                apply_hints=apply_hints,
                owner_apply_hints=apply_hints,
            )
