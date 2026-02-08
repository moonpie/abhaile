"""Unit tests for vault templates renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from renderers.vault_templates import render_vault_agent_configs
from utils.errors import RenderError


def _write(path: Path, content: str) -> None:
    """Helper to write file with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestRenderVaultAgentConfigs:
    """Tests for render_vault_agent_configs()."""

    def test_no_services_does_nothing(self, tmp_path: Path) -> None:
        """Empty services list does nothing."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        render_vault_agent_configs(
            "phobos",
            [],
            network,
            config_root,
            output_dir,
        )

        # No output should be generated
        assert not output_dir.exists()

    def test_no_base_service_does_nothing(self, tmp_path: Path) -> None:
        """Services without vault_agent base definition are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
composition:
  container:
    named_volumes: []
""",
        )

        render_vault_agent_configs(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
        )

        # No vault-agent output
        assert not (output_dir / "vault-agent").exists()

    def test_render_base_no_templates(self, tmp_path: Path) -> None:
        """Base service without templates renders only base config."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """vault {
  address = "https://vault.svc:8200"
}

{% for t in vault_agent_templates %}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.destination }}"
  perms       = "{{ t.perms }}"
}
{% endfor %}
""",
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent"],
            network,
            config_root,
            output_dir,
        )

        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        assert config_file.exists()

        content = config_file.read_text()
        assert "vault {" in content
        assert 'address = "https://vault.svc:8200"' in content
        # No templates rendered (empty loop)

    def test_render_base_with_templates(self, tmp_path: Path) -> None:
        """Base service aggregates templates from other services."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        # Base service
        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """vault { address = "https://vault.svc:8200" }

{% for t in vault_agent_templates %}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.dest }}"
  perms       = "{{ t.perms }}"
}
{% endfor %}
""",
        )

        # Service with template
        _write(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  vault_agent:
    templates:
      - source: templates/tls-cert.pem.ctmpl
        out: /srv/caddy/dmz/tls/cert.pem
        perms: "0640"
""",
        )

        _write(
            config_root / "services" / "caddy-dmz" / "templates" / "tls-cert.pem.ctmpl",
            '{{ with secret "pki/issue/dmz" "common_name=*.example.com" }}{{ .Data.certificate }}{{ end }}',
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent", "caddy-dmz"],
            network,
            config_root,
            output_dir,
        )

        # Config file should exist
        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        assert config_file.exists()

        content = config_file.read_text()
        assert "vault {" in content
        assert "template {" in content
        assert "/agent/templates/tls-cert.pem.ctmpl" in content
        assert "/agent/out/srv/caddy/dmz/tls/cert.pem" in content
        assert '"0640"' in content

        # Template file should be copied
        template_file = (
            output_dir / "vault-agent" / "srv/vault/agent/templates/tls-cert.pem.ctmpl"
        )
        assert template_file.exists()
        template_content = template_file.read_text()
        assert "pki/issue/dmz" in template_content

    def test_multiple_templates_deterministic_order(self, tmp_path: Path) -> None:
        """Multiple templates are aggregated in mapping order by service."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """{% for t in vault_agent_templates %}
# {{ t.comment }}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.dest }}"
  perms       = "{{ t.perms }}"
}
{% endfor %}
""",
        )

        # Service vaultwarden (mapping order after authelia)
        _write(
            config_root / "services" / "vaultwarden" / "service.yaml",
            """name: vaultwarden
composition:
  vault_agent:
    templates:
      - source: templates/smtp-pw.txt.ctmpl
        out: /srv/vaultwarden/secrets/smtp-pw.txt
        perms: "0400"
""",
        )

        _write(
            config_root
            / "services"
            / "vaultwarden"
            / "templates"
            / "smtp-pw.txt.ctmpl",
            '{{ with secret "secret/smtp" }}{{ .Data.password }}{{ end }}',
        )

        # Service authelia (mapping order before vaultwarden)
        _write(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  vault_agent:
    templates:
      - source: templates/jwt.txt.ctmpl
        out: /srv/authelia/secrets/jwt.txt
        perms: "0600"
""",
        )

        _write(
            config_root / "services" / "authelia" / "templates" / "jwt.txt.ctmpl",
            '{{ with secret "secret/authelia" }}{{ .Data.jwt }}{{ end }}',
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent", "authelia", "vaultwarden"],
            network,
            config_root,
            output_dir,
        )

        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        content = config_file.read_text()

        # Check order: authelia before vaultwarden (mapping order)
        authelia_pos = content.find("authelia")
        vaultwarden_pos = content.find("vaultwarden")
        assert authelia_pos < vaultwarden_pos

    def test_multiple_templates_from_same_service(self, tmp_path: Path) -> None:
        """Service with multiple template files includes all."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """{% for t in vault_agent_templates %}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.dest }}"
}
{% endfor %}
""",
        )

        _write(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  vault_agent:
    templates:
      - source: templates/jwt.txt.ctmpl
        out: /srv/authelia/secrets/jwt.txt
        perms: "0600"
      - source: templates/storage-key.txt.ctmpl
        out: /srv/authelia/secrets/storage-key.txt
        perms: "0600"
""",
        )

        _write(
            config_root / "services" / "authelia" / "templates" / "jwt.txt.ctmpl",
            "JWT content",
        )

        _write(
            config_root
            / "services"
            / "authelia"
            / "templates"
            / "storage-key.txt.ctmpl",
            "Storage key content",
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent", "authelia"],
            network,
            config_root,
            output_dir,
        )

        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        content = config_file.read_text()

        assert "/agent/templates/jwt.txt.ctmpl" in content
        assert "/agent/templates/storage-key.txt.ctmpl" in content
        assert "/agent/out/srv/authelia/secrets/jwt.txt" in content
        assert "/agent/out/srv/authelia/secrets/storage-key.txt" in content

        # Both templates copied
        assert (
            output_dir / "vault-agent" / "srv/vault/agent/templates/jwt.txt.ctmpl"
        ).exists()
        assert (
            output_dir
            / "vault-agent"
            / "srv/vault/agent/templates/storage-key.txt.ctmpl"
        ).exists()

    def test_service_prefix_in_template_path(self, tmp_path: Path) -> None:
        """Template source with service-name/ prefix is stripped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """{% for t in vault_agent_templates %}
template { source = "{{ t.source }}" }
{% endfor %}
""",
        )

        _write(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  vault_agent:
    templates:
      - source: caddy-dmz/templates/cert.pem.ctmpl
        out: /srv/caddy/dmz/tls/cert.pem
        perms: "0640"
""",
        )

        _write(
            config_root / "services" / "caddy-dmz" / "templates" / "cert.pem.ctmpl",
            "cert content",
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent", "caddy-dmz"],
            network,
            config_root,
            output_dir,
        )

        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        content = config_file.read_text()

        # Service prefix stripped in source path
        assert "/agent/templates/cert.pem.ctmpl" in content

        # Template copied correctly
        template_file = (
            output_dir / "vault-agent" / "srv/vault/agent/templates/cert.pem.ctmpl"
        )
        assert template_file.exists()

    def test_network_placeholder_resolution(self, tmp_path: Path) -> None:
        """Network placeholders in template variables are resolved."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {
            "services": {
                "vault": {
                    "address": "10.100.0.1/32",
                },
            },
        }

        _write(
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
        variables:
          vault_address: "%%network.services.vault.address | strip_cidr%%"
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            """vault {
  address = "https://{{ service.config.vault_address }}:8200"
}
""",
        )

        render_vault_agent_configs(
            "phobos",
            ["vault-agent"],
            network,
            config_root,
            output_dir,
        )

        config_file = output_dir / "vault-agent" / "srv/vault/agent/config/config.hcl"
        content = config_file.read_text()

        # Placeholder resolved and CIDR stripped
        assert 'address = "https://10.100.0.1:8200"' in content
        assert "/32" not in content

    def test_missing_base_template_raises_error(self, tmp_path: Path) -> None:
        """Missing base template source raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

    def test_missing_service_template_raises_error(self, tmp_path: Path) -> None:
        """Missing service template file raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        _write(
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

    def test_base_missing_source_or_destination(self, tmp_path: Path) -> None:
        """Base definition missing source or destination raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
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
        network = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_vault_agent_configs(
                "phobos",
                ["nonexistent"],
                network,
                config_root,
                output_dir,
            )

    def test_template_missing_required_fields(self, tmp_path: Path) -> None:
        """Template definition missing required fields raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network = {}

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "config" / "config.hcl.j2",
            "vault { }",
        )

        _write(
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

        _write(
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
