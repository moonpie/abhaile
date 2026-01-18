"""
Pytest configuration for tests/unit/.

Layer-specific fixtures for **unit tests only**. Global fixtures live in
tests/conftest.py; module-specific fixtures should stay in the test module
itself. This keeps the hierarchy consistent (global → layer → module) and
avoids duplicate definitions.
"""

__all__ = [
    "mock_network_config",
    "mock_service_metadata",
    "mock_mapping_config",
    "inventory_dir",
    "rendered_dir",
]

import json
import pytest
import yaml


@pytest.fixture
def mock_network_config(tmp_path):
    """Provide a standard network.yaml structure for testing.

    **Source:** Hardcoded minimal valid network configuration
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/render/* (network topology tests)
    - tests/unit/validate/* (validation tests)

    **Refresh:** Update if network.yaml schema changes or new
    test scenarios require different VLAN/host configurations.

    Returns:
        tuple: (network_dict, yaml_path) where network_dict contains
        vlans, hosts, services, and dns sections.
    """
    network = {
        "vlans": {
            "vlan1": {"id": 10},
            "vlan2": {"id": 20},
        },
        "hosts": {
            "phobos": {
                "physical_device": "enp0s31f6",
                "interfaces": {"enp0s31f6": {"vlan": "vlan1"}},
            },
            "deimos": {
                "physical_device": "enp0s31f6",
                "interfaces": {"enp0s31f6": {"vlan": "vlan2"}},
            },
        },
        "services": {
            "svc1": {"address": "172.20.10.5/32", "vlan": "vlan1"},
            "svc2": {"address": "172.20.20.5/32", "vlan": "vlan2"},
        },
        "dns": {"zones": []},
    }
    yaml_path = tmp_path / "network.yaml"
    yaml_path.write_text(yaml.safe_dump(network))
    return network, yaml_path


@pytest.fixture
def mock_service_metadata(tmp_path):
    """Provide standard service metadata for testing.

    **Source:** Hardcoded service.yaml metadata structures
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/render/test_service_builder.py
    - tests/unit/inventory/* (service classification tests)

    **Refresh:** Update if service.yaml schema changes or new
    service types are added (currently: container, service).

    Returns:
        tuple: (services_meta_dict, json_path) with service definitions
        including type, network mode, and ports.
    """
    services_meta = {
        "svc1": {
            "type": "container",
            "network": "ipvlan-l2",
            "ports": [8080],
        },
        "svc2": {
            "type": "service",
            "network": "service-32",
            "ports": [443],
        },
    }
    meta_path = tmp_path / "services_meta.json"
    meta_path.write_text(json.dumps(services_meta))
    return services_meta, meta_path


@pytest.fixture
def mock_mapping_config(tmp_path):
    """Provide a standard mapping.yaml structure for testing.

    **Source:** Hardcoded minimal valid mapping configuration
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/render/* (mapping-driven rendering tests)
    - tests/unit/validate/* (mapping validation tests)

    **Refresh:** Update if mapping.yaml schema changes or new
    deployment patterns are added.

    Returns:
        tuple: (mapping_dict, yaml_path) with host-to-services mappings
        in standard abhaile format.
    """
    mapping = {
        "abhaile": [
            {"phobos": ["svc1", "svc2"]},
            {"deimos": ["svc1"]},
        ]
    }
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(yaml.safe_dump(mapping))
    return mapping, mapping_path


@pytest.fixture
def inventory_dir(tmp_path):
    """Create a mock inventory directory structure.

    **Source:** Generated temporary directory with empty inventory files
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/inventory/* (inventory generation tests)

    **Refresh:** Update if inventory output format changes or new
    inventory files are added to the generation workflow.

    Creates standard inventory/*.json files with empty content for
    testing inventory generation logic.
    """
    inv = tmp_path / "inventory"
    inv.mkdir()

    # Create standard inventory files with empty content
    (inv / "hosts.json").write_text(json.dumps({}))
    (inv / "services.json").write_text(json.dumps({}))
    (inv / "services_meta.json").write_text(json.dumps({}))
    (inv / "network.json").write_text(json.dumps({"hosts": {}}))
    (inv / "systemd_units.json").write_text(json.dumps({}))

    return inv


@pytest.fixture
def rendered_dir(tmp_path):
    """Create a mock rendered output directory structure.

    **Source:** Generated temporary directory with host subdirectories
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/render/* (output validation tests)
    - tests/unit/inventory/* (rendered artifact collection tests)

    **Refresh:** Update if rendered output structure changes or new
    host directories are added.

    Creates out/rendered/<host>/ structure with systemd-networkd/ and
    services/ subdirectories for phobos and deimos.
    """
    rendered = tmp_path / "rendered"
    rendered.mkdir()

    for host in ["phobos", "deimos"]:
        host_dir = rendered / host
        (host_dir / "systemd-networkd").mkdir(parents=True)
        (host_dir / "services").mkdir(parents=True)

    return rendered
