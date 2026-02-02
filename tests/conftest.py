"""Shared pytest fixtures for Abhaile render/apply tests."""

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Add lib/python to path for imports during tests
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib" / "python"))


@pytest.fixture
def tmp_repo():
    """Create a temporary repository structure with minimal config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)

        # Create directory structure
        (repo_root / "config" / "services").mkdir(parents=True)
        (repo_root / "schemas").mkdir(parents=True)
        (repo_root / "scripts" / "lib" / "python").mkdir(parents=True)

        # Create paths.ini
        paths_ini = repo_root / "scripts" / "paths.ini"
        paths_ini.write_text(
            "[paths]\n"
            "output_root_default = /var/lib/abhaile\n"
            "target_root = /\n"
            "config_root = config\n"
            "schemas_root = schemas\n"
            "hosts_subdir = hosts\n"
            "services_subdir = services\n"
            "rendered_dir_name = rendered\n"
            "state_dir_name = state\n"
            "systemd_networkd_dir = systemd-networkd\n"
            "systemd_resolved_dir = systemd-resolved\n"
            "systemd_units_dir = systemd-units\n"
        )

        yield repo_root


@pytest.fixture
def tmp_repo_with_config(tmp_repo):
    """Create a temporary repo with valid sample configuration."""
    repo_root = tmp_repo

    # Minimal valid mapping.yaml
    mapping = {
        "abhaile": [
            {"phobos": ["test-service"]},
            {"deimos": ["test-service"]},
        ]
    }
    (repo_root / "config" / "mapping.yaml").write_text(yaml.dump(mapping))

    # Minimal valid network.yaml
    network = {
        "vlans": {
            "services": {
                "id": 20,
                "cidr": "172.20.20.0/24",
                "gateway": "172.20.20.1",
                "ipvlanl2_range": "172.20.20.200-172.20.20.254",
            }
        },
        "dns": {"zones": []},
        "hosts": {
            "phobos": {
                "physical_device": "eth0",
                "interfaces": {
                    "eth0": {
                        "address": "172.20.20.10/24",
                        "vlan": "services",
                    }
                },
            },
            "deimos": {
                "physical_device": "eth0",
                "interfaces": {
                    "eth0": {
                        "address": "172.20.20.11/24",
                        "vlan": "services",
                    }
                },
            },
        },
        "services": {
            "test-service": {
                "address": "172.20.20.200/32",
                "vlan": "services",
            }
        },
    }
    (repo_root / "config" / "network.yaml").write_text(yaml.dump(network))

    # Minimal valid service.yaml
    service_dir = repo_root / "config" / "services" / "test-service"
    service_dir.mkdir(parents=True)
    service = {
        "name": "test-service",
        "type": "container",
        "mode": "rootless",
        "network": "ipvlan-l2",
    }
    (service_dir / "service.yaml").write_text(yaml.dump(service))

    # Create schema files (minimal valid schemas)
    mapping_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["abhaile"],
        "properties": {
            "abhaile": {
                "type": "array",
                "items": {"type": "object"},
            }
        },
        "additionalProperties": False,
    }
    (repo_root / "schemas" / "mapping.schema.json").write_text(
        json.dumps(mapping_schema)
    )

    network_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "vlans": {"type": "object"},
            "dns": {"type": "object"},
            "hosts": {"type": "object"},
            "services": {"type": "object"},
        },
    }
    (repo_root / "schemas" / "network.schema.json").write_text(
        json.dumps(network_schema)
    )

    service_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "mode": {"type": "string"},
            "network": {"type": "string"},
        },
    }
    (repo_root / "schemas" / "service.schema.json").write_text(
        json.dumps(service_schema)
    )

    return repo_root


@pytest.fixture
def tmp_output(tmp_path):
    """Create a temporary output directory."""
    return tmp_path / "output"
