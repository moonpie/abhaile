"""Unified configuration file renderer for host and service compositions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.errors import RenderError


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
    jinja_env = Environment(
        loader=FileSystemLoader(template_base_dir),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

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
            except Exception as exc:
                raise RenderError(
                    f"Failed to render template '{template_path}': {exc}"
                ) from exc

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered_content)

        else:
            # Static file
            source_path = config_root / source
            if not source_path.exists():
                raise RenderError(f"Source file not found: {source_path}")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)


def _strip_cidr(address: str) -> str:
    """Jinja2 filter to strip CIDR notation from IP address.

    Args:
        address: IP address with CIDR (e.g., "172.20.20.10/24")

    Returns:
        IP address without CIDR (e.g., "172.20.20.10")
    """
    return address.split("/")[0] if "/" in address else address
