"""Placeholder tests for vault template rendering error paths.

These tests are stubs for future implementation.
Actual vault template rendering is tested in test_vault_templates_base.py.
"""

import pytest


def test_missing_vault_template(tmp_path):
    """Test that missing vault-agent template file raises RenderError."""
    from abhaile.renderers.vault_templates.copying import copy_vault_agent_templates
    from abhaile.renderers.vault_templates.discovery import VaultTemplateSpec
    from abhaile.utils.errors import RenderError

    services_root = tmp_path / "services"
    output_dir = tmp_path / "output"
    service_dir = services_root / "test-service"
    service_dir.mkdir(parents=True)

    # Create spec pointing to non-existent template
    specs = [
        VaultTemplateSpec(
            service="test-service",
            source="templates/missing.ctmpl",
            out="config/output.conf",
            perms="0644",
        )
    ]

    with pytest.raises(RenderError) as exc_info:
        copy_vault_agent_templates(
            specs=specs,
            services_root=services_root,
            output_dir=output_dir,
            templates_host_root="/vault/templates",
            templates_mount_root="/vault/templates",
            out_mount_root="/vault/out",
            base_service="vault-agent",
        )

    error = str(exc_info.value)
    assert "Vault-agent template not found" in error
    assert "missing.ctmpl" in error
    assert "test-service" in error
