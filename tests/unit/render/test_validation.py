"""Tests for tools/render/validation.py"""

import pytest
import yaml
from pathlib import Path

from tools.render.validate import (
    ValidationError,
    validate_mapping_hosts,
    validate_template_sources,
    validate_network_uniqueness,
    validate_all,
    validate_or_raise,
)
from tools.common.core import PathConfig


class TestValidateMappingHosts:
    """Tests for mapping→hosts validation."""

    def test_valid_mapping(self):
        """Should return no errors for valid mapping."""
        mapping = {"abhaile": [{"phobos": ["svc1"]}, {"deimos": ["svc2"]}]}
        network = {"hosts": {"phobos": {}, "deimos": {}}}
        errors = validate_mapping_hosts(mapping, network)
        assert errors == []

    def test_unknown_host(self):
        """Should error if mapping references undefined host."""
        mapping = {"abhaile": [{"unknown-host": ["svc1"]}]}
        network = {"hosts": {"phobos": {}}}
        errors = validate_mapping_hosts(mapping, network)
        assert len(errors) == 1
        assert "unknown-host" in errors[0]
        assert "not in network.yaml" in errors[0]

    def test_non_list_services(self):
        """Should error if services is not a list."""
        mapping = {"abhaile": [{"phobos": "not-a-list"}]}
        network = {"hosts": {"phobos": {}}}
        errors = validate_mapping_hosts(mapping, network)
        assert len(errors) == 1
        assert "Expected list of services" in errors[0]

    def test_empty_mapping(self):
        """Should handle empty mapping gracefully."""
        mapping = {}
        network = {"hosts": {"phobos": {}}}
        errors = validate_mapping_hosts(mapping, network)
        assert errors == []


class TestValidateTemplateSources:
    """Tests for template source file existence validation."""

    def test_valid_templates(self, tmp_path: Path):
        """Should return no errors when all templates exist."""
        services_dir = tmp_path / "services"
        svc_dir = services_dir / "svc1"
        svc_dir.mkdir(parents=True)

        (svc_dir / "template.j2").write_text("content")
        (svc_dir / "service.yaml").write_text(
            yaml.dump({"config": [{"source": {"template": "template.j2"}}]})
        )

        errors = validate_template_sources(services_dir, {"svc1"})
        assert errors == []

    def test_missing_template(self, tmp_path: Path):
        """Should error if referenced template doesn't exist."""
        services_dir = tmp_path / "services"
        svc_dir = services_dir / "svc1"
        svc_dir.mkdir(parents=True)

        (svc_dir / "service.yaml").write_text(
            yaml.dump({"config": [{"source": {"template": "missing.j2"}}]})
        )

        errors = validate_template_sources(services_dir, {"svc1"})
        assert len(errors) == 1
        assert "missing.j2" in errors[0]
        assert "missing template" in errors[0]

    def test_missing_vault_template(self, tmp_path: Path):
        """Should error if vault-agent template doesn't exist."""
        services_dir = tmp_path / "services"
        svc_dir = services_dir / "svc1"
        svc_dir.mkdir(parents=True)

        (svc_dir / "service.yaml").write_text(
            yaml.dump(
                {"vault_agent": {"templates": [{"source": "vault-missing.ctmpl"}]}}
            )
        )

        errors = validate_template_sources(services_dir, {"svc1"})
        assert len(errors) == 1
        assert "vault-missing.ctmpl" in errors[0]

    def test_missing_static_source(self, tmp_path: Path):
        """Should error if static source file doesn't exist."""
        services_dir = tmp_path / "services"
        svc_dir = services_dir / "svc1"
        svc_dir.mkdir(parents=True)

        (svc_dir / "service.yaml").write_text(
            yaml.dump({"config": [{"source": "static-missing.conf"}]})
        )

        errors = validate_template_sources(services_dir, {"svc1"})
        assert len(errors) == 1
        assert "static-missing.conf" in errors[0]

    def test_skips_service_without_metadata(self, tmp_path: Path):
        """Should skip services that don't have service.yaml."""
        services_dir = tmp_path / "services"
        errors = validate_template_sources(services_dir, {"nonexistent-svc"})
        # Should not error - render will catch missing service.yaml
        assert errors == []


class TestValidateNetworkUniqueness:
    """Tests for IP address last-octet uniqueness validation."""

    def test_unique_addresses(self):
        """Should return no errors for unique last octets."""
        network = {
            "services": {
                "svc1": {"address": "172.20.1.10"},
                "svc2": {"address": "172.20.1.20"},
            }
        }
        errors = validate_network_uniqueness(network)
        assert errors == []

    def test_duplicate_last_octet(self):
        """Should error on duplicate last octets in same VLAN."""
        network = {
            "services": {
                "svc1": {"address": "172.20.1.10", "vlan": "vlan1"},
                "svc2": {
                    "address": "172.20.1.20",
                    "vlan": "vlan1",
                },  # Different octet, OK
                "svc3": {
                    "address": "172.20.1.10",
                    "vlan": "vlan1",
                },  # Duplicate .10 in same VLAN
            }
        }
        errors = validate_network_uniqueness(network)
        assert len(errors) == 1
        assert "Duplicate last-octet" in errors[0]


class TestValidateAll:
    """Tests for validate_all() orchestrator."""

    def test_valid_config(self, tmp_path: Path):
        """Should return no errors for completely valid config."""
        # Create minimal valid config
        (tmp_path / ".git").mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        mapping = {"abhaile": [{"phobos": ["svc1"]}]}
        (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

        network = {
            "hosts": {"phobos": {}},
            "services": {"svc1": {"address": "172.20.1.10"}},
        }
        (config_dir / "network.yaml").write_text(yaml.dump(network))

        svc_dir = config_dir / "services" / "svc1"
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(yaml.dump({"type": "infrastructure"}))

        paths = PathConfig(
            repo_root=tmp_path,
            config_root=config_dir,
            output_root=tmp_path / "out" / "rendered",
            state_root=tmp_path / "out" / "state",
            secrets_root=tmp_path / "secrets",
        )

        errors = validate_all(paths)
        assert errors == []

    def test_multiple_errors(self, tmp_path: Path):
        """Should collect multiple validation errors."""
        (tmp_path / ".git").mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Invalid: unknown host + duplicate IP in same VLAN
        mapping = {"abhaile": [{"unknown-host": ["svc1"]}]}
        (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

        network = {
            "hosts": {"phobos": {}},
            "services": {
                "svc1": {"address": "172.20.1.10", "vlan": "vlan1"},
                "svc2": {
                    "address": "172.20.1.10",
                    "vlan": "vlan1",
                },  # Duplicate last octet in same VLAN
            },
        }
        (config_dir / "network.yaml").write_text(yaml.dump(network))

        (config_dir / "services").mkdir()

        paths = PathConfig(
            repo_root=tmp_path,
            config_root=config_dir,
            output_root=tmp_path / "out" / "rendered",
            state_root=tmp_path / "out" / "state",
            secrets_root=tmp_path / "secrets",
        )

        errors = validate_all(paths)
        assert len(errors) >= 2  # Should have both errors


class TestValidateOrRaise:
    """Tests for validate_or_raise() helper."""

    def test_raises_on_errors(self, tmp_path: Path):
        """Should raise ValidationError with error details."""
        (tmp_path / ".git").mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        mapping = {"abhaile": [{"unknown-host": ["svc1"]}]}
        (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

        network = {"hosts": {"phobos": {}}}
        (config_dir / "network.yaml").write_text(yaml.dump(network))

        (config_dir / "services").mkdir()

        paths = PathConfig(
            repo_root=tmp_path,
            config_root=config_dir,
            output_root=tmp_path / "out" / "rendered",
            state_root=tmp_path / "out" / "state",
            secrets_root=tmp_path / "secrets",
        )

        with pytest.raises(ValidationError) as exc_info:
            validate_or_raise(paths)

        assert "Configuration validation failed" in str(exc_info.value)
        assert "unknown-host" in str(exc_info.value)

    def test_no_raise_on_success(self, tmp_path: Path):
        """Should not raise if validation passes."""
        (tmp_path / ".git").mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        mapping = {"abhaile": [{"phobos": ["svc1"]}]}
        (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

        network = {
            "hosts": {"phobos": {}},
            "services": {"svc1": {"address": "172.20.1.10"}},
        }
        (config_dir / "network.yaml").write_text(yaml.dump(network))

        svc_dir = config_dir / "services" / "svc1"
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(yaml.dump({"type": "infrastructure"}))

        paths = PathConfig(
            repo_root=tmp_path,
            config_root=config_dir,
            output_root=tmp_path / "out" / "rendered",
            state_root=tmp_path / "out" / "state",
            secrets_root=tmp_path / "secrets",
        )

        # Should not raise
        validate_or_raise(paths)
