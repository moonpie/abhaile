"""Shared helper utilities for quadlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple

from abhaile.utils.artifact_collector import ArtifactCollector
from abhaile.utils.errors import RenderError

# Maps quadlet file suffix to artifact kind used in the manifest
_QUADLET_KIND_BY_SUFFIX: dict[str, str] = {
    ".container": "quadlet.container",
    ".pod": "quadlet.pod",
    ".image": "quadlet.image",
    ".build": "quadlet.build",
    ".volume": "quadlet.volume",
    ".network": "quadlet.network",
}


def _quadlet_kind_from_filename(filename: str) -> str:
    """Return the quadlet artifact kind for a given output filename.

    Args:
        filename: Quadlet output filename (e.g., ``blocky.container``).

    Returns:
        Artifact kind string (e.g., ``quadlet.container``).
    """
    suffix = Path(filename).suffix
    return _QUADLET_KIND_BY_SUFFIX.get(suffix, "quadlet.unknown")


def _quadlet_unit_name(filename: str) -> str:
    """Return the derived systemd unit name for a quadlet file.

    Containers and pods map ``{stem}.{ext}`` → ``{stem}.service``.
    Volumes, networks, images, and builds append the extension type as a
    suffix to distinguish them from container units.

    Args:
        filename: Quadlet output filename (e.g., ``blocky.container``).

    Returns:
        Systemd unit name (e.g., ``blocky.service``).
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    if suffix in (".container", ".pod"):
        return f"{stem}.service"
    ext_word = suffix.lstrip(".")
    return f"{stem}-{ext_word}.service"


def _register_quadlet_artifact(
    *,
    collector: ArtifactCollector,
    rendered_root: Path,
    output_path: Path,
    target_path: str,
    kind: str,
    owner_ref: str,
    content: str,
    apply_hints: dict[str, Any] | None = None,
    owner_apply_hints: dict[str, Any] | None = None,
    owner_requires: list[str] | None = None,
) -> None:
    """Register a single quadlet artifact with the collector.

    Creates the owner if it has not yet been registered for this render.

    Args:
        collector: Artifact collector to register with.
        rendered_root: Root of the rendered output tree (for render_path computation).
        output_path: Absolute path of the written artifact.
        target_path: Live host target path for this artifact.
        kind: Artifact kind (e.g., ``quadlet.container``).
        owner_ref: Owner identifier (e.g., ``unit:blocky.service``).
        content: File content string.
        apply_hints: Optional apply-phase hints.
    """
    render_path = output_path.relative_to(rendered_root).as_posix()
    if owner_ref not in collector.get_all_owners():
        collector.register_owner(
            name=owner_ref,
            description=f"Quadlet unit {owner_ref}",
            apply_hints=owner_apply_hints,
            requires=owner_requires or [],
        )
    collector.register_artifact(
        render_path=render_path,
        target_path=target_path,
        kind=kind,
        owner_ref=owner_ref,
        content=content,
        apply_hints=apply_hints,
    )


def _validate_trailing_newline(path: Path, *, context: str) -> None:
    """Validate text source file has a trailing newline.

    Args:
        path: Source file path to validate.
        context: Human-readable context for error messages.

    Raises:
        RenderError: If file is non-empty and does not end with a newline.
    """
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        raise RenderError(f"{context} must end with a trailing newline: {path}")


def _discover_build_image_files(
    quadlets_dir: Path,
    service: str,
    container_name: str | None = None,
) -> Tuple[Path | None, Path | None, str | None, str | None]:
    """Discover build/image files and compute target filenames.

    Args:
        quadlets_dir: Directory containing quadlet files.
        service: Service name.
        container_name: Optional container name (for pod containers).

    Returns:
        Tuple of (build_path, image_path, build_filename, image_filename).
    """
    build_files = sorted(
        path for path in quadlets_dir.rglob("build.build") if path.parent == quadlets_dir
    )
    image_files = sorted(
        path for path in quadlets_dir.rglob("image.image") if path.parent == quadlets_dir
    )

    if container_name:
        build_error = (
            "Multiple build.build files found for container "
            f"'{container_name}' in pod service '{service}'"
        )
        image_error = (
            "Multiple image.image files found for container "
            f"'{container_name}' in pod service '{service}'"
        )
        name_base = f"{service}-app-{container_name}"
    else:
        build_error = f"Multiple build.build files found for service '{service}'"
        image_error = f"Multiple image.image files found for service '{service}'"
        name_base = service

    if len(build_files) > 1:
        raise RenderError(build_error)
    if len(image_files) > 1:
        raise RenderError(image_error)

    build_path = build_files[0] if build_files else None
    image_path = image_files[0] if image_files else None

    build_filename = f"{name_base}.build" if build_path else None
    image_filename = f"{name_base}.image" if image_path else None

    return build_path, image_path, build_filename, image_filename
