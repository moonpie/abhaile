"""Copying helpers for vault-agent template rendering."""

from __future__ import annotations

from pathlib import Path

from abhaile.renderers.vault_templates.discovery import VaultTemplateSpec
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import normalize_service_prefixed_path


def copy_vault_agent_templates(
    specs: list[VaultTemplateSpec],
    services_root: Path,
    output_dir: Path,
    templates_host_root: str,
    templates_mount_root: str,
    out_mount_root: str,
    base_service: str,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> list[dict[str, str]]:
    """Copy vault-agent templates and return template metadata.

    Args:
        specs: Template specs in mapping order.
        services_root: Path to config/services directory.
        output_dir: Path to rendered services root.
        templates_host_root: Host path for templates named volume.
        templates_mount_root: Mount path for templates named volume.
        out_mount_root: Mount path for output named volume.
        base_service: Vault-agent service name (output target).

    Returns:
        List of template dicts with source, dest, perms keys.

    Raises:
        RenderError: If a referenced template file doesn't exist.
    """
    templates: list[dict[str, str]] = []

    for spec in specs:
        relative_source = normalize_service_prefixed_path(spec.service, spec.source)
        source_path = services_root / spec.service / relative_source

        if not source_path.exists():
            raise RenderError(
                f"Vault-agent template not found: {spec.source} in service '{spec.service}'"
            )

        if relative_source.startswith("templates/"):
            template_rel = relative_source[len("templates/") :]
        else:
            template_rel = relative_source

        dest_path = output_dir / base_service / templates_host_root.lstrip("/") / template_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(
            source_path.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )

        from abhaile.renderers.vault_templates.rendering import _register_vault_artifact

        _register_vault_artifact(
            collector=collector,
            rendered_root=rendered_root,
            output_path=dest_path,
            target_path=_join_mount_path(templates_host_root, template_rel),
            kind="vault.template",
            content=dest_path.read_text(encoding="utf-8"),
            contributor_ref=f"service:{spec.service}",
            apply_hints={
                "write_order": "before-config",
                "restart_mode": "restart",
                "rootless": True,
                "podman_user": "abhaile",
            },
        )

        templates.append(
            {
                "source": _join_mount_path(templates_mount_root, template_rel),
                "dest": _join_mount_path(out_mount_root, spec.out),
                "perms": spec.perms,
            }
        )

    return templates


def _join_mount_path(root: str, path: str) -> str:
    """Join a root mount path with a relative path."""
    root_clean = root.rstrip("/")
    path_clean = path.lstrip("/")
    return f"{root_clean}/{path_clean}"
