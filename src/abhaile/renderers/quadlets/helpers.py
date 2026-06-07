"""Shared helper utilities for quadlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.models.kinds import KIND_FAMILIES
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError

# Derived from KIND_FAMILIES["quadlet"] — maps file suffix to artifact kind
_QUADLET_KIND_BY_SUFFIX: dict[str, str] = {
    f".{kind.split('.', 1)[1]}": kind for kind in KIND_FAMILIES["quadlet"]
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
    replace: bool = False,
) -> None:
    """Register a single quadlet artifact with the collector.

    Creates the owner if it has not yet been registered for this render.
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
        replace=replace,
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
) -> tuple[Path | None, Path | None, str | None, str | None]:
    """Discover build/image files and compute target filenames."""
    name_base = f"{service}-app-{container_name}" if container_name else service

    _build = quadlets_dir / "build.build"
    _image = quadlets_dir / "image.image"

    build_path = _build if _build.exists() else None
    image_path = _image if _image.exists() else None

    build_filename = f"{name_base}.build" if build_path else None
    image_filename = f"{name_base}.image" if image_path else None

    return build_path, image_path, build_filename, image_filename


def _resolve_composition_definition(
    key: str,
    service: str,
    composition: dict[str, Any],
    services_root: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a composition definition by key, walking includes if needed."""
    from abhaile.utils.composition import resolve_composition

    definition = composition.get(key)
    if definition:
        return definition, service

    config_root = services_root.parent
    includes = composition.get("include", []) or []
    for included in includes:
        included_composition = resolve_composition(
            service_name=included,
            config_root=config_root,
            merge_strategy="deep",
        )
        definition = included_composition.get(key)
        if definition:
            return definition, included

    return None, None
