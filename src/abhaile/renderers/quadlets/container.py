"""Container quadlet rendering helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from abhaile.renderers.quadlets.helpers import (
    _quadlet_kind_from_filename,
    _quadlet_unit_name,
    _register_quadlet_artifact,
    _validate_trailing_newline,
)
from abhaile.utils.artifact_collector import ArtifactCollector
from abhaile.utils.composition import resolve_composition
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env

# Template variable requirements for quadlet templates
TEMPLATE_REQUIREMENTS = {
    "container.container.j2": {
        "optional": {"image", "build"},
        "required": set(),
    }
}


def _validate_template_variables(template_name: str, template_text: str) -> None:
    """Validate that a template contains required variables.

    Args:
        template_name: Name of the template (e.g., 'container.container.j2').
        template_text: Full content of the template.

    Raises:
        RenderError: If required variables are missing.
    """
    requirements = TEMPLATE_REQUIREMENTS.get(template_name)
    if not requirements:
        return

    required = requirements.get("required", set())
    optional = requirements.get("optional", set())

    # Extract all template variables from {{ ... }}
    import re

    var_pattern = r"\{\{\s*(\w+)"
    template_vars = set(re.findall(var_pattern, template_text))

    # Check required variables
    missing = required - template_vars
    if missing:
        raise RenderError(
            f"Template {template_name} missing required variables: {', '.join(missing)}"
        )

    # Check for conditional optional variables
    # If any optional variable is used, all must be satisfied or explicitly handled
    for var in optional:
        if var in template_vars:
            # This variable is used; ensure it will be provided
            pass  # Will be caught if not provided in render context


def _resolve_container_definition(
    service: str,
    composition: Dict[str, Any],
    services_root: Path,
) -> Tuple[Dict[str, Any] | None, str | None]:
    """Resolve container definition, checking includes recursively.

    Args:
        service: Service name.
        composition: Service composition dict.
        services_root: Path to config/services directory.
    Returns:
        Tuple of (container_def, source_service) or (None, None) if not found.
    """
    # Check direct definition first
    container_def = composition.get("container")
    if container_def:
        return container_def, service

    config_root = services_root.parent
    includes = composition.get("include", []) or []
    for included in includes:
        included_composition = resolve_composition(
            service_name=included,
            config_root=config_root,
            merge_strategy="deep",
        )
        container_def = included_composition.get("container")
        if container_def:
            return container_def, included

    return None, None


def _render_service_quadlet_files(
    service: str,
    quadlets_dir: Path,
    output_dir: Path,
    network: Dict[str, Any],
    host: str,
    volume_lines: List[str],
    build_filename: str | None,
    image_filename: str | None,
    *,
    output_root: Path | None = None,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
    container_owner_requires: List[str] | None = None,
) -> None:
    """Render container quadlet files for a service into the output directory."""
    jinja_env = create_jinja_env(quadlets_dir)
    is_rootless = bool(output_root and not output_root.as_posix().startswith("/etc"))
    apply_hints: Dict[str, Any] = {"rootless": is_rootless}
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

            # Use robust validation instead of string-contains checks
            _validate_template_variables("container.container.j2", template_text)

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
