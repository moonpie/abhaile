"""Tests for vault template rendering error paths."""

from pathlib import Path

import pytest

from abhaile.renderers.vault_templates.copying import copy_vault_agent_templates
from abhaile.renderers.vault_templates.discovery import VaultTemplateSpec
from abhaile.utils.errors import RenderError


def test_missing_vault_template(tmp_path: Path) -> None:
    """Missing vault-agent template source raises RenderError."""
    services_root = tmp_path / "config" / "services"
    output_dir = tmp_path / "output" / "services"

    services_root.mkdir(parents=True, exist_ok=True)

    specs = [
        VaultTemplateSpec(
            service="authelia",
            source="templates/missing.ctmpl",
            out="/srv/authelia/secrets/jwt.txt",
            perms="0600",
        )
    ]

    with pytest.raises(RenderError, match="Vault-agent template not found"):
        copy_vault_agent_templates(
            specs=specs,
            services_root=services_root,
            output_dir=output_dir,
            templates_host_root="/srv/vault/agent/templates",
            templates_mount_root="/agent/templates",
            out_mount_root="/agent/out",
            base_service="vault-agent",
        )
