"""Unit tests for vault templates error handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.vault_templates.rendering import render_vault_agent_configs
from abhaile.utils.errors import RenderError


class TestRenderVaultAgentConfigs:
    """Tests for render_vault_agent_configs()."""

    def test_missing_base_template_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing base template source raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
composition:
  container:
    named_volumes:
      - name: templates
        host_path: /srv/vault/agent/templates
        mount_path: /agent/templates
      - name: out
        host_path: /srv/vault/agent/out
        mount_path: /agent/out
  vault_agent:
    base:
      source:
        template: config/config.hcl.j2
        variables: {}
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        # Don't create the template

        with pytest.raises(RenderError, match="Vault-agent base template not found"):
            render_vault_agent_configs(
                "phobos",
                ["vault-agent"],
                network,
                config_root,
                output_dir,
            )

    def test_missing_service_template_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing service template file raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
composition:
  container:
    named_volumes:
      - name: templates
        host_path: /srv/vault/agent/templates
        mount_path: /agent/templates
      - name: out
        host_path: /srv/vault/agent/out
        mount_path: /agent/out
  vault_agent:
    base:
      source:
        template: config/config.hcl.j2
        variables: {}
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        write_file(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  vault_agent:
    templates:
      - source: templates/missing.ctmpl
        out: /srv/authelia/secrets/jwt.txt
        perms: "0600"
""",
        )

        # Don't create the template file

        with pytest.raises(RenderError, match="Vault-agent template not found"):
            render_vault_agent_configs(
                "phobos",
                ["vault-agent", "authelia"],
                network,
                config_root,
                output_dir,
            )

    def test_base_missing_source_or_destination(self, tmp_path: Path, write_file: Any) -> None:
        """Base definition missing source or destination raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
composition:
  container:
    named_volumes:
      - name: templates
        host_path: /srv/vault/agent/templates
        mount_path: /agent/templates
      - name: out
        host_path: /srv/vault/agent/out
        mount_path: /agent/out
  vault_agent:
    base:
      source:
        template: config/config.hcl.j2
        variables: {}
      # Missing destination
""",
        )

        write_file(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        with pytest.raises(RenderError, match="missing source or destination"):
            render_vault_agent_configs(
                "phobos",
                ["vault-agent"],
                network,
                config_root,
                output_dir,
            )

    def test_service_without_yaml_raises_error(self, tmp_path: Path) -> None:
        """Service without service.yaml raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_vault_agent_configs(
                "phobos",
                ["nonexistent"],
                network,
                config_root,
                output_dir,
            )

    def test_template_missing_required_fields(self, tmp_path: Path, write_file: Any) -> None:
        """Template definition missing required fields raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
composition:
  container:
    named_volumes:
      - name: templates
        host_path: /srv/vault/agent/templates
        mount_path: /agent/templates
      - name: out
        host_path: /srv/vault/agent/out
        mount_path: /agent/out
  vault_agent:
    base:
      source:
        template: config/config.hcl.j2
        variables: {}
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        write_file(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  vault_agent:
    templates:
      - source: templates/jwt.txt.ctmpl
        # Missing 'out' field
        perms: "0600"
""",
        )

        write_file(
            config_root / "services" / "authelia" / "templates" / "jwt.txt.ctmpl",
            "content",
        )

        with pytest.raises(RenderError, match="Invalid vault_agent template entry"):
            render_vault_agent_configs(
                "phobos",
                ["vault-agent", "authelia"],
                network,
                config_root,
                output_dir,
            )

    def test_template_missing_perms_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Template definition missing perms raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
composition:
  container:
    named_volumes:
      - name: templates
        host_path: /srv/vault/agent/templates
        mount_path: /agent/templates
      - name: out
        host_path: /srv/vault/agent/out
        mount_path: /agent/out
  vault_agent:
    base:
      source:
        template: config/config.hcl.j2
        variables: {}
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        write_file(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  vault_agent:
    templates:
      - source: templates/jwt.txt.ctmpl
        out: /srv/authelia/secrets/jwt.txt
        # Missing 'perms' field
""",
        )

        write_file(
            config_root / "services" / "authelia" / "templates" / "jwt.txt.ctmpl",
            "content",
        )

        with pytest.raises(RenderError, match="missing perms"):
            render_vault_agent_configs(
                "phobos",
                ["vault-agent", "authelia"],
                network,
                config_root,
                output_dir,
            )
