"""Rendering helpers for vault-agent templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from abhaile.renderers.vault_templates.copying import copy_vault_agent_templates
from abhaile.renderers.vault_templates.discovery import (
    collect_vault_agent_template_specs,
    find_base_vault_agent_service,
    resolve_vault_agent_volume_paths,
)
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import normalize_service_prefixed_path
from abhaile.utils.placeholders import resolve_placeholders
from abhaile.utils.templating import create_jinja_env


def render_vault_agent_configs(
    host: str,
    host_services: List[str],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render aggregated vault-agent configuration for the host.

    Finds the base vault-agent service (with vault_agent.base) on the current host,
    then aggregates vault_agent.templates from services ONLY on the same host
    (since vault-agent writes to local filesystem).

    Args:
        host: Host name (e.g., phobos, deimos).
        host_services: Services mapped to this specific host.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_dir: Path to rendered services root (rendered/services).

    Raises:
        RenderError: If rendering fails or validation errors occur.
    """
    if not host_services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_service = find_base_vault_agent_service(services_root, host_services)

    if not base_service:
        return

    service_yaml = services_root / base_service / "service.yaml"
    service_data = read_yaml(service_yaml) or {}

    vault_agent_def = service_data.get("composition", {}).get("vault_agent", {})
    base = vault_agent_def.get("base")

    if not base:
        raise RenderError(f"Service '{base_service}' missing vault_agent.base definition")

    source = base.get("source")
    destination = base.get("destination")

    if not source or not destination:
        raise RenderError(
            f"Service '{base_service}' vault_agent.base missing source or destination"
        )

    templates_host_root, templates_mount_root, out_mount_root = resolve_vault_agent_volume_paths(
        base_service, service_data
    )

    specs = collect_vault_agent_template_specs(host_services, services_root)
    templates = copy_vault_agent_templates(
        specs,
        services_root,
        output_dir,
        templates_host_root,
        templates_mount_root,
        out_mount_root,
        base_service,
    )

    _render_base_config(
        base_service=base_service,
        source=source,
        destination=destination,
        templates=templates,
        network=network,
        services_root=services_root,
        output_dir=output_dir,
    )


def _render_base_config(
    base_service: str,
    source: Dict[str, Any],
    destination: str,
    templates: List[Dict[str, str]],
    network: Dict[str, Any],
    services_root: Path,
    output_dir: Path,
) -> None:
    """Render the base vault-agent configuration file."""
    template_path = source.get("template")
    variables = source.get("variables", {})
    if not isinstance(variables, dict):
        raise RenderError(
            f"Service '{base_service}' vault_agent.base.source.variables must be a dict"
        )

    if not template_path:
        raise RenderError(f"Service '{base_service}' vault_agent.base.source missing template")

    relative_template = normalize_service_prefixed_path(base_service, template_path)
    full_template_path = services_root / base_service / relative_template

    if not full_template_path.exists():
        raise RenderError(
            f"Vault-agent base template not found: {template_path} in service '{base_service}'"
        )

    jinja_env = create_jinja_env(full_template_path.parent)

    context: Dict[str, Any] = {
        "vault_agent_templates": templates,
        "service": {"config": {}},
    }

    resolved_vars = resolve_placeholders(variables, network)
    for key, value in resolved_vars.items():
        context["service"]["config"][key] = value

    template = jinja_env.get_template(full_template_path.name)
    rendered = template.render(**context)

    output_path = output_dir / base_service / destination.lstrip("/")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
