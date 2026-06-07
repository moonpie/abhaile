"""Discovery helpers for vault-agent template rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abhaile.utils.composition import walk_service_includes
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError


@dataclass(frozen=True)
class VaultTemplateSpec:
    """Validated vault-agent template definition."""

    service: str
    source: str
    out: str
    perms: str


def find_base_vault_agent_service(
    services_root: Path,
    host_services: list[str],
) -> str | None:
    """Find the vault-agent service that defines base configuration."""
    for service in host_services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        vault_agent_def = service_data.get("composition", {}).get("vault_agent", {})

        if "base" in vault_agent_def:
            return service

    return None


def collect_vault_agent_template_specs(
    host_services: list[str],
    services_root: Path,
) -> list[VaultTemplateSpec]:
    """Collect vault-agent template specs from services on this host."""
    specs: list[VaultTemplateSpec] = []
    visited: set[str] = set()

    for service in host_services:
        ordered_services = walk_service_includes(
            service,
            config_root=services_root.parent,
            visited=visited,
            stack=[],
        )
        for service_name in ordered_services:
            specs.extend(
                _collect_vault_template_specs_for_service(
                    service=service_name,
                    services_root=services_root,
                )
            )

    return specs


def _collect_vault_template_specs_for_service(
    service: str,
    services_root: Path,
) -> list[VaultTemplateSpec]:
    """Collect vault_agent template specs from a single service."""
    service_yaml = services_root / service / "service.yaml"
    if not service_yaml.exists():
        raise RenderError(f"Missing service definition: {service_yaml}")

    service_data = read_yaml(service_yaml) or {}
    composition = service_data.get("composition", {})
    vault_agent_def = composition.get("vault_agent", {})
    template_defs = vault_agent_def.get("templates", []) or []

    specs: list[VaultTemplateSpec] = []
    for template_def in template_defs:
        source = template_def.get("source")
        out = template_def.get("out")
        perms = template_def.get("perms")

        if not source or not out:
            raise RenderError(
                f"Invalid vault_agent template entry in service '{service}': {template_def}"
            )
        if perms is None:
            raise RenderError(
                f"Vault_agent template entry missing perms in service '{service}': {template_def}"
            )

        specs.append(
            VaultTemplateSpec(
                service=service,
                source=str(source),
                out=str(out),
                perms=str(perms),
            )
        )

    return specs


def resolve_vault_agent_volume_paths(
    base_service: str,
    service_data: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Resolve vault-agent templates/out host and mount paths from named volumes."""
    container_def = service_data.get("composition", {}).get("container", {})
    named_volumes = container_def.get("named_volumes", []) or []

    templates_host_root = None
    templates_mount_root = None
    out_host_root = None
    out_mount_root = None

    for volume in named_volumes:
        if not isinstance(volume, dict):
            continue
        name = volume.get("name")
        host_path = volume.get("host_path")
        mount_path = volume.get("mount_path")

        if name == "templates":
            templates_host_root = host_path
            templates_mount_root = mount_path
        elif name == "out":
            out_host_root = host_path
            out_mount_root = mount_path

    if (
        not templates_host_root
        or not templates_mount_root
        or not out_host_root
        or not out_mount_root
    ):
        raise RenderError(
            f"Service '{base_service}' must define container.named_volumes for "
            "'templates' (host_path + mount_path) and 'out' (host_path + mount_path)"
        )

    return templates_host_root, templates_mount_root, out_host_root, out_mount_root
