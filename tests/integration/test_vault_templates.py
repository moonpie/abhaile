"""Integration tests for vault templates rendering with actual config."""

from pathlib import Path

import pytest

from abhaile.renderers.vault_templates.rendering import render_vault_agent_configs
from abhaile.utils.config import read_yaml

pytestmark = pytest.mark.integration


class TestVaultTemplatesIntegration:
    """Integration tests using actual repository configuration."""

    def test_vault_agent_approle_config_for_phobos_and_deimos(self, tmp_path: Path) -> None:
        """Render phobos and deimos vault-agent configs with native AppRole auto-auth."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        network_yaml = config_root / "network.yaml"
        if not mapping_yaml.exists() or not network_yaml.exists():
            pytest.skip("Test requires mapping.yaml and network.yaml")

        mapping = read_yaml(mapping_yaml)
        network = read_yaml(network_yaml)
        host_services: dict[str, list[str]] = {}
        for entries in mapping.get("abhaile", []):
            for host, services in entries.items():
                if isinstance(services, list):
                    host_services[host] = services

        for host in ("phobos", "deimos"):
            services = host_services.get(host, [])
            if "vault-agent" not in services:
                pytest.skip(f"vault-agent not mapped to {host}")

            output_dir = tmp_path / host / "services"
            render_vault_agent_configs(host, services, network, config_root, output_dir)

            config_file = output_dir / "vault-agent" / "srv/vault/agent/config.hcl"
            content = config_file.read_text(encoding="utf-8")

            assert 'method "approle"' in content
            assert 'role_id_file_path = "/agent/role-id"' in content
            assert 'secret_id_file_path = "/agent/secret-id"' in content
            assert "remove_secret_id_file_after_reading = false" in content
            assert 'method "token_file"' not in content
            assert "token_file_path" not in content

    @pytest.mark.slow
    def test_render_actual_phobos_vault_templates(self, tmp_path: Path) -> None:
        """Test rendering vault-agent for phobos with actual config."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        # Load mapping to get phobos services
        mapping = read_yaml(mapping_yaml)
        phobos_services = []
        for entries in mapping.get("abhaile", []):
            if "phobos" in entries:
                phobos_services = entries["phobos"]
                break

        if not phobos_services:
            pytest.skip("No services mapped to phobos")

        # Load network config
        network = read_yaml(network_yaml)

        output_dir = tmp_path / "services"

        render_vault_agent_configs(
            "phobos",
            phobos_services,
            network,
            config_root,
            output_dir,
        )

        # Verify vault-agent config output
        config_file = output_dir / "vault-agent" / "srv/vault/agent/config.hcl"
        if not config_file.exists():
            # vault-agent may not be on phobos
            pytest.skip("vault-agent not mapped to phobos")

        content = config_file.read_text()

        # Should have vault configuration
        assert "vault" in content

        # Check for services with vault_agent templates on phobos
        services_with_templates = []
        for service in phobos_services:
            service_yaml = config_root / "services" / service / "service.yaml"
            if service_yaml.exists():
                data = read_yaml(service_yaml) or {}
                vault_agent = data.get("composition", {}).get("vault_agent", {})
                if "templates" in vault_agent:
                    services_with_templates.append(service)

        # Verify template blocks if any services have templates
        if services_with_templates:
            assert "template {" in content

            # Verify template files were copied
            for service in services_with_templates:
                service_yaml = config_root / "services" / service / "service.yaml"
                data = read_yaml(service_yaml)
                templates = data.get("composition", {}).get("vault_agent", {}).get("templates", [])

                for template_def in templates:
                    source = template_def.get("source", "")
                    if source:
                        # Strip service prefix if present
                        if source.startswith(f"{service}/"):
                            source = source[len(service) + 1 :]

                        template_filename = Path(source).name
                        copied_template = (
                            output_dir
                            / "vault-agent"
                            / "srv/vault/agent/templates"
                            / template_filename
                        )
                        assert (
                            copied_template.exists()
                        ), f"Template {template_filename} from {service} should be copied"

                        # Verify template path in config
                        expected_path = f"/agent/templates/{template_filename}"
                        assert expected_path in content, f"Config should reference {expected_path}"

    def test_vault_templates_deterministic(self, tmp_path: Path) -> None:
        """Verify vault templates rendering is deterministic across runs."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        # Use deimos as it should have vault-agent
        mapping = read_yaml(mapping_yaml)
        deimos_services = []
        for entries in mapping.get("abhaile", []):
            if "deimos" in entries:
                deimos_services = entries["deimos"]
                break

        if not deimos_services or "vault-agent" not in deimos_services:
            pytest.skip("vault-agent not mapped to deimos")

        network = read_yaml(network_yaml)

        # Render twice
        output_dir1 = tmp_path / "run1" / "services"
        output_dir2 = tmp_path / "run2" / "services"

        render_vault_agent_configs("deimos", deimos_services, network, config_root, output_dir1)
        render_vault_agent_configs("deimos", deimos_services, network, config_root, output_dir2)

        # Compare outputs
        config_file1 = output_dir1 / "vault-agent" / "srv/vault/agent/config.hcl"
        config_file2 = output_dir2 / "vault-agent" / "srv/vault/agent/config.hcl"

        assert config_file1.exists() and config_file2.exists()
        assert (
            config_file1.read_text() == config_file2.read_text()
        ), "Vault-agent config should be deterministic"

    @pytest.mark.slow
    def test_authelia_templates_on_correct_host(self, tmp_path: Path) -> None:
        """Test that authelia vault templates only appear on host running authelia."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        network_yaml = config_root / "network.yaml"

        if not mapping_yaml.exists() or not network_yaml.exists():
            pytest.skip("Test requires mapping.yaml and network.yaml")

        authelia_yaml = config_root / "services" / "authelia" / "service.yaml"
        if not authelia_yaml.exists():
            pytest.skip("Test requires authelia service")

        # Check if authelia has vault_agent templates
        authelia_data = read_yaml(authelia_yaml)
        authelia_templates = (
            authelia_data.get("composition", {}).get("vault_agent", {}).get("templates", [])
        )
        if not authelia_templates:
            pytest.skip("authelia doesn't define vault_agent templates")

        # Find which host runs authelia
        mapping = read_yaml(mapping_yaml)
        authelia_host = None
        other_host = None
        host_services: dict[str, list[str]] = {}

        for entries in mapping.get("abhaile", []):
            for host, services in entries.items():
                if not isinstance(services, list):
                    continue
                host_services[host] = services
                if "authelia" in services:
                    authelia_host = host
                elif "vault-agent" in services:
                    other_host = host

        if not authelia_host or not other_host:
            pytest.skip("Need at least two hosts with vault-agent")

        assert authelia_host is not None
        assert other_host is not None

        network = read_yaml(network_yaml)

        # Render vault-agent on authelia's host
        output_authelia = tmp_path / "authelia_host" / "services"
        render_vault_agent_configs(
            authelia_host,
            host_services[authelia_host],
            network,
            config_root,
            output_authelia,
        )

        # Render vault-agent on other host
        output_other = tmp_path / "other_host" / "services"
        render_vault_agent_configs(
            other_host,
            host_services[other_host],
            network,
            config_root,
            output_other,
        )

        # Check authelia templates are only on authelia's host
        authelia_config = output_authelia / "vault-agent" / "srv/vault/agent/config.hcl"
        if authelia_config.exists():
            authelia_content = authelia_config.read_text()
            # Should have authelia templates
            for template_def in authelia_templates:
                source = template_def.get("source", "")
                if source:
                    filename = Path(source).name
                    expected_path = f"/agent/templates/{filename}"
                    assert (
                        expected_path in authelia_content
                    ), f"Authelia's vault-agent should include {expected_path}"

        # Check authelia templates are NOT on other host
        other_config = output_other / "vault-agent" / "srv/vault/agent/config.hcl"
        if other_config.exists():
            other_content = other_config.read_text()
            # Should NOT have authelia templates
            for template_def in authelia_templates:
                source = template_def.get("source", "")
                if source:
                    filename = Path(source).name
                    expected_path = f"/agent/templates/{filename}"
                    assert (
                        expected_path not in other_content
                    ), f"Other host's vault-agent should NOT include {expected_path}"
