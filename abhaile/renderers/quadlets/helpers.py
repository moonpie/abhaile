"""Shared helper utilities for quadlet rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from abhaile.utils.errors import RenderError


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
