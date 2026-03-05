"""Unit tests for vault templates base rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.vault_templates import render_vault_agent_configs


class TestRenderVaultAgentConfigs:
    """Tests for render_vault_agent_configs()."""

    def test_no_services_does_nothing(self, tmp_path: Path) -> None:
        """Empty services list does nothing."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        render_vault_agent_configs(
            "phobos",
            [],
            network,
            config_root,
            output_dir,
        )

        # No output should be generated
        assert not output_dir.exists()

    def test_no_base_service_does_nothing(self, tmp_path: Path, write_file: Any) -> None:
        """Services without vault_agent base definition are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        write_file(
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

    def test_render_base_no_templates(self, tmp_path: Path, write_file: Any) -> None:
        """Base service without templates renders only base config."""
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

    def test_render_base_with_templates(self, tmp_path: Path, write_file: Any) -> None:
        """Base service aggregates templates from other services."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {}

        # Base service
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
        write_file(
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

        write_file(
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
        template_file = output_dir / "vault-agent" / "srv/vault/agent/templates/tls-cert.pem.ctmpl"
        assert template_file.exists()
        template_content = template_file.read_text()
        assert "pki/issue/dmz" in template_content
