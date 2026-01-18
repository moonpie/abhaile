"""Vault Agent template collection and staging."""

from pathlib import Path
from typing import Any
import shutil

from tools.common.core import get_logger

logger = get_logger(__name__)


def _resolve_template_source(source: str, svc: str, services_dir: Path) -> Path | None:
    """Resolve a vault-agent template source path.

    Accepts:
    - absolute paths
    - paths relative to the service directory (svc/<path>)
    - service-prefixed paths already including the service name

    Args:
        source: Template source path.
        svc: Service name.
        services_dir: Root services directory.

    Returns:
        Path | None: Resolved path if found, else None.
    """
    candidate = Path(source)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    for base in (services_dir / svc, services_dir):
        candidate = base / source
        if candidate.exists():
            return candidate

    return None


def collect_vault_agent_templates(
    host_services: list[str],
    services_meta: dict[str, Any],
    services_dir: Path,
    output_root: Path,
    hostname: str,
) -> tuple[list[dict[str, Any]], list[tuple[Path, Path]]]:
    """Collect Vault-Agent templates from deployed services.

    Scans services for vault_agent.templates definitions and prepares them
    for inclusion in Vault Agent's config.hcl.

    Args:
        host_services: List of service names on this host.
        services_meta: Service metadata dictionary.
        services_dir: Root services directory.
        output_root: Rendered output root.
        hostname: Name of host being rendered.

    Returns:
        tuple: (templates, copy_list) where:
            - templates: list of template config dicts for vault-agent
            - copy_list: list of (source, destination) Path tuples to stage
    """
    templates: list[dict[str, Any]] = []
    copy_list: list[tuple[Path, Path]] = []

    for svc in host_services:
        svc_meta = services_meta.get(svc, {})
        vault_agent_config = svc_meta.get("vault_agent", {})
        template_list = vault_agent_config.get("templates", [])

        for tmpl in template_list:
            source = tmpl.get("source")
            if not source:
                continue

            src_path = _resolve_template_source(str(source), svc, services_dir)
            if not src_path:
                logger.warning(
                    "Vault Agent template not found: %s",
                    services_dir / svc / source,
                )
                continue

            # Destination lives under /srv/vault/agent/templates to match mount
            template_name = src_path.name
            dest_path = (
                output_root
                / hostname
                / "services"
                / "vault-agent"
                / "srv"
                / "vault"
                / "agent"
                / "templates"
                / template_name
            )

            template_config = {
                "source": f"/agent/templates/{template_name}",
                "dest": f"/agent/out/{tmpl.get('out', template_name)}",
                "perms": tmpl.get("perms", "0640"),
            }
            if "command" in tmpl:
                template_config["command"] = tmpl["command"]

            templates.append(template_config)
            copy_list.append((src_path, dest_path))

    return templates, copy_list


def stage_vault_agent_templates(copy_list: list[tuple[Path, Path]]) -> None:
    """Stage Vault Agent template files to output directory.

    Args:
        copy_list: List of (source, destination) path tuples
    """
    for src, dest in copy_list:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        logger.info("Staged Vault Agent template: %s", dest)
