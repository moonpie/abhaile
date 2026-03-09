"""Unified configuration file renderer for host and service compositions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import TemplateError, TemplateNotFound, UndefinedError

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

        # Calculate output path (strip leading / to make relative)
        relative_dest = destination.lstrip("/")
        output_path = output_dir / relative_dest

        if "source" not in entry:
            # Directory-only entry: ensure destination exists
            output_path.mkdir(parents=True, exist_ok=True)
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

        else:
            # Static file
            source_path = config_root / source
            if not source_path.exists():
                raise RenderError(
                    f"Source file not found: {source_path} (destination: {destination})"
                )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)
