"""Unified configuration file renderer for host and service compositions."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import TemplateError, TemplateNotFound, UndefinedError

from abhaile.renderers.metadata import classify_config_artifact
from abhaile.utils.artifact_collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.templating import create_jinja_env


def filter_config_entries_by_destination_prefix(
    entries: List[Dict[str, Any]],
    prefix: str,
    *,
    include: bool = True,
) -> List[Dict[str, Any]]:
    """Filter config entries by destination prefix.

    Args:
        entries: Config entries to filter.
        prefix: Destination prefix to match.
        include: If True, include entries with matching prefix; if False, exclude them.

    Returns:
        Filtered list of entries.
    """
    if not entries:
        return []

    def _matches(entry: Dict[str, Any]) -> bool:
        """Return True when entry destination starts with the prefix."""
        destination = entry.get("destination")
        if destination is None:
            destination = ""
        if not isinstance(destination, str):
            return False
        return destination.startswith(prefix)

    if include:
        return [entry for entry in entries if _matches(entry)]
    return [entry for entry in entries if not _matches(entry)]


def render_config_entries(
    entries: List[Dict[str, Any]],
    config_root: Path,
    template_base_dir: Path,
    output_dir: Path,
    context: Dict[str, Any],
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
    default_owner_ref: str = "owner:unknown",
    classify_artifact: Callable[[str, str, bool], tuple[str, str]] | None = None,
) -> None:
    """Render configuration entries (static, templated, or directories).

    Processes composition.config[] entries according to common.schema.json:
    - Static files: {source: "path/to/file", destination: "/abs/path"}
    - Templates: {source: {template: "path.j2", variables: {}}, destination: "/abs/path"}
    - Directories: {destination: "/abs/path"} (ensure exists, no source)

    Args:
        entries: List of config entries from composition.config.
        config_root: Path to config/ directory (for resolving static sources).
        template_base_dir: Base directory for Jinja2 template loader.
        output_dir: Output directory root (destinations are relative to this).
        context: Jinja2 template context (network, host_name, service_name, etc.).

    Raises:
        RenderError: If source file/template missing or rendering fails.
    """
    if not entries:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Setup Jinja2 environment
    jinja_env = create_jinja_env(template_base_dir)

    for entry in entries:
        destination = entry.get("destination")
        if not destination:
            raise RenderError(f"Config entry missing destination: {entry}")
        apply_hints = _entry_apply_hints(entry)

        # Calculate output path (strip leading / to make relative)
        relative_dest = destination.lstrip("/")
        output_path = output_dir / relative_dest

        if "source" not in entry:
            # Directory-only entry: ensure destination exists
            output_path.mkdir(parents=True, exist_ok=True)
            _register_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=output_path,
                destination=destination,
                default_owner_ref=default_owner_ref,
                content="",
                is_directory=True,
                contributor_ref=_entry_contributor_ref(entry),
                apply_hints=apply_hints,
                classify_artifact=classify_artifact,
            )
            continue

        source = entry["source"]

        if isinstance(source, dict):
            # Templated file
            template_path = source.get("template")
            if not template_path:
                raise RenderError(f"Template entry missing 'template' key: {source}")

            variables = source.get("variables", {})

            # Merge explicit variables with context
            template_context = {**context, **variables}
            if "service_name" in context:
                template_context.setdefault(
                    "service",
                    {
                        "name": context["service_name"],
                        "config": variables,
                    },
                )

            try:
                template = jinja_env.get_template(template_path)
                rendered_content = template.render(**template_context)
            except (TemplateError, TemplateNotFound, UndefinedError) as exc:
                raise RenderError(
                    f"Failed to render template '{template_path}' to '{destination}': {exc}"
                ) from exc

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered_content, encoding="utf-8", newline="\n")
            _register_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=output_path,
                destination=destination,
                default_owner_ref=default_owner_ref,
                content=rendered_content,
                is_directory=False,
                contributor_ref=_entry_contributor_ref(entry),
                apply_hints=apply_hints,
                classify_artifact=classify_artifact,
            )

        else:
            # Static file
            source_path = config_root / source
            if not source_path.exists():
                raise RenderError(
                    f"Source file not found: {source_path} (destination: {destination})"
                )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)
            _register_artifact(
                collector=collector,
                rendered_root=rendered_root,
                output_path=output_path,
                destination=destination,
                default_owner_ref=default_owner_ref,
                content=output_path.read_bytes(),
                is_directory=False,
                contributor_ref=_entry_contributor_ref(entry),
                apply_hints=apply_hints,
                classify_artifact=classify_artifact,
            )


def _entry_apply_hints(entry: Dict[str, Any]) -> dict[str, Any] | None:
    """Return internal precomputed apply hints when present."""
    precomputed = entry.get("_abhaile_apply_hints")
    if isinstance(precomputed, dict):
        return dict(precomputed) or None
    return None


def _entry_contributor_ref(entry: Dict[str, Any]) -> str | None:
    """Return internal contributor marker when present."""
    contributor_ref = entry.get("_abhaile_contributor_ref")
    if not isinstance(contributor_ref, str) or not contributor_ref:
        return None
    return contributor_ref


def _register_artifact(
    *,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
    output_path: Path,
    destination: str,
    default_owner_ref: str,
    content: bytes | str,
    is_directory: bool,
    contributor_ref: str | None,
    apply_hints: dict[str, Any] | None,
    classify_artifact: Callable[[str, str, bool], tuple[str, str]] | None,
) -> None:
    """Register rendered artifact metadata when collection is enabled."""
    if collector is None or rendered_root is None:
        return

    render_path = output_path.relative_to(rendered_root).as_posix()
    classifier = classify_artifact or (
        lambda dest, owner_ref, directory: classify_config_artifact(
            dest,
            default_owner_ref=owner_ref,
            is_directory=directory,
        )
    )
    kind, owner_ref = classifier(destination, default_owner_ref, is_directory)

    collector.register_artifact(
        render_path=render_path,
        target_path=destination,
        kind=kind,
        owner_ref=owner_ref,
        content=content,
        is_directory=is_directory,
        replace=True,
        contributor_ref=contributor_ref,
        apply_hints=apply_hints,
    )
