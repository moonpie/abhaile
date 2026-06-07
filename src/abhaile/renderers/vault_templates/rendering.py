"""Rendering helpers for vault-agent templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from abhaile.renderers.vault_templates.copying import copy_vault_agent_templates
from abhaile.renderers.vault_templates.discovery import (
    VaultTemplateSpec,
    collect_vault_agent_template_specs,
    find_base_vault_agent_service,
    resolve_vault_agent_volume_paths,
)
from abhaile.utils.config import read_yaml
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import normalize_service_prefixed_path
from abhaile.utils.placeholders import resolve_placeholders
from abhaile.utils.templating import create_jinja_env

LOG = logging.getLogger(__name__)


def render_vault_agent_configs(
    host: str,
    host_services: list[str],
    network: dict[str, Any],
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
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

    templates_host_root, templates_mount_root, out_host_root, out_mount_root = (
        resolve_vault_agent_volume_paths(base_service, service_data)
    )

    specs = collect_vault_agent_template_specs(host_services, services_root)
    LOG.debug("render.vault_agent host=%s templates=%d", host, len(specs))
    templates = copy_vault_agent_templates(
        specs,
        services_root,
        output_dir,
        templates_host_root,
        templates_mount_root,
        out_mount_root,
        base_service,
        collector=collector,
        rendered_root=rendered_root,
    )
    _ensure_vault_output_directories(
        specs=specs,
        out_host_root=out_host_root,
        base_service=base_service,
        service_data=service_data,
        output_dir=output_dir,
        collector=collector,
        rendered_root=rendered_root,
    )

    _render_base_config(
        base_service=base_service,
        source=source,
        destination=destination,
        templates=templates,
        network=network,
        services_root=services_root,
        output_dir=output_dir,
        collector=collector,
        rendered_root=rendered_root,
    )


def _render_base_config(
    base_service: str,
    source: dict[str, Any],
    destination: str,
    templates: list[dict[str, str]],
    network: dict[str, Any],
    services_root: Path,
    output_dir: Path,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
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

    context: dict[str, Any] = {
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
    _register_vault_artifact(
        collector=collector,
        rendered_root=rendered_root,
        output_path=output_path,
        target_path=destination,
        kind="vault.config",
        content=rendered,
        apply_hints={
            "write_order": "after-templates",
            "restart_mode": "restart",
            "rootless": True,
            "podman_user": "abhaile",
        },
    )


def _register_vault_artifact(
    *,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
    output_path: Path,
    target_path: str,
    kind: str,
    owner_ref: str = "service:vault-agent",
    content: str,
    is_directory: bool = False,
    contributor_ref: str | None = None,
    apply_hints: dict[str, Any] | None = None,
) -> None:
    """Register a vault-agent artifact and ensure its owner exists."""
    if collector is None or rendered_root is None:
        return

    if owner_ref not in collector.get_all_owners():
        collector.register_owner(
            name=owner_ref,
            description="vault-agent service",
        )

    collector.register_artifact(
        render_path=output_path.relative_to(rendered_root).as_posix(),
        target_path=target_path,
        kind=kind,
        owner_ref=owner_ref,
        content=content,
        is_directory=is_directory,
        replace=True,
        contributor_ref=contributor_ref,
        apply_hints=apply_hints,
    )


def _ensure_vault_output_directories(
    *,
    specs: list[VaultTemplateSpec],
    out_host_root: str,
    base_service: str,
    service_data: dict[str, Any],
    output_dir: Path,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
) -> None:
    """Ensure runtime output parent directories are rendered and tracked for apply."""
    directories: set[str] = {str(Path(out_host_root).as_posix())}

    for spec in specs:
        runtime_target = Path(_join_host_path(out_host_root, spec.out))
        directories.add(runtime_target.parent.as_posix())

    owner, group = _vault_runtime_owner_group(service_data)
    for directory in sorted(directories):
        output_path = output_dir / base_service / directory.lstrip("/")
        output_path.mkdir(parents=True, exist_ok=True)
        _register_vault_artifact(
            collector=collector,
            rendered_root=rendered_root,
            output_path=output_path,
            target_path=directory,
            kind="service.directory",
            content="",
            is_directory=True,
            apply_hints={
                "owner": owner,
                "group": group,
                "mode": "0750",
            },
        )


def _vault_runtime_owner_group(service_data: dict[str, Any]) -> tuple[str, str]:
    """Resolve host runtime owner/group for vault output directories."""
    podman = service_data.get("podman")
    owner = "root"
    if isinstance(podman, dict):
        podman_user = podman.get("user")
        if isinstance(podman_user, str) and podman_user:
            owner = podman_user

    group = owner if owner != "root" else "root"
    return owner, group


def _join_host_path(root: str, path: str) -> str:
    """Join an absolute host root path with a possibly rooted relative path."""
    return f"{root.rstrip('/')}/{path.lstrip('/')}"
