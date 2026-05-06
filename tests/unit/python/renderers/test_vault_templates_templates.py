"""Unit tests for vault templates aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.vault_templates.rendering import render_vault_agent_configs


class TestRenderVaultAgentConfigs:
    """Tests for render_vault_agent_configs()."""

    def test_multiple_templates_deterministic_order(self, tmp_path: Path, write_file: Any) -> None:
        """Multiple templates are aggregated in mapping order by service."""
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
            """{% for t in vault_agent_templates %}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.dest }}"
  perms       = "{{ t.perms }}"
}
{% endfor %}
""",
        )

        # Service vaultwarden (mapping order after authelia)
        write_file(
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

        write_file(
            config_root / "services" / "vaultwarden" / "templates" / "smtp-pw.txt.ctmpl",
            '{{ with secret "secret/smtp" }}{{ .Data.password }}{{ end }}',
        )

        # Service authelia (mapping order before vaultwarden)
        write_file(
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

        write_file(
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

    def test_multiple_templates_from_same_service(self, tmp_path: Path, write_file: Any) -> None:
        """Service with multiple template files includes all."""
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
            """{% for t in vault_agent_templates %}
template {
  source      = "{{ t.source }}"
  destination = "{{ t.dest }}"
}
{% endfor %}
""",
        )

        write_file(
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

        write_file(
            config_root / "services" / "authelia" / "templates" / "jwt.txt.ctmpl",
            "JWT content",
        )

        write_file(
            config_root / "services" / "authelia" / "templates" / "storage-key.txt.ctmpl",
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
        assert (output_dir / "vault-agent" / "srv/vault/agent/templates/jwt.txt.ctmpl").exists()
        assert (
            output_dir / "vault-agent" / "srv/vault/agent/templates/storage-key.txt.ctmpl"
        ).exists()

    def test_service_prefix_in_template_path(self, tmp_path: Path, write_file: Any) -> None:
        """Template source with service-name/ prefix is stripped."""
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
            """{% for t in vault_agent_templates %}
template { source = "{{ t.source }}" }
{% endfor %}
""",
        )

        write_file(
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

        write_file(
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
        template_file = output_dir / "vault-agent" / "srv/vault/agent/templates/cert.pem.ctmpl"
        assert template_file.exists()

    def test_network_placeholder_resolution(self, tmp_path: Path, write_file: Any) -> None:
        """Network placeholders in template variables are resolved."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"
        network: dict[str, Any] = {
            "services": {
                "vault": {
                    "address": "10.100.0.1/32",
                },
            },
        }

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
        variables:
          vault_address: "%%network.services.vault.address | strip_cidr%%"
      destination: /srv/vault/agent/config/config.hcl
""",
        )

        write_file(
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
