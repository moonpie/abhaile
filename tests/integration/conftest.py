"""
Pytest configuration for tests/integration/.

Provides integration test fixtures for real filesystem I/O, subprocess execution,
and full workflow scenarios.
"""

import pytest
import yaml


@pytest.fixture
def integration_tmp_repo(tmp_path):
    """
    Create a temporary directory with a valid abhaile repo structure
    (minimal config, network, mapping files for testing).
    """
    # Create .git directory so PathConfig can find repo root
    (tmp_path / ".git").mkdir()

    # Copy paths.ini from real repo (required for PathConfig)
    import shutil
    from pathlib import Path

    real_repo_root = Path(__file__).resolve().parents[2]
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    shutil.copy(real_repo_root / "tools" / "paths.ini", tools_dir / "paths.ini")

    # Dev mode is auto-detected: tmp_path != /opt/abhaile, so it's dev mode
    # No need to create out/ directory

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Minimal mapping
    mapping = {"abhaile": [{"phobos": ["svc1"]}, {"deimos": ["svc2"]}]}
    (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

    # Minimal network
    network = {
        "vlans": {
            "vlan1": {"id": 10, "subnet": "172.20.10.0/24"},
            "vlan2": {"id": 20, "subnet": "172.20.20.0/24"},
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
            "svc1": {"address": "172.20.10.10/32", "vlan": "vlan1"},
            "svc2": {"address": "172.20.20.10/32", "vlan": "vlan2"},
        },
    }
    (config_dir / "network.yaml").write_text(yaml.dump(network))

    # Minimal services
    for svc in ["svc1", "svc2"]:
        svc_dir = config_dir / "services" / svc
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(
            f"type: infrastructure\nname: {svc}\nnetwork: host"
        )

    # Host templates
    for host in ["phobos", "deimos"]:
        host_dir = config_dir / "hosts" / host / "systemd-networkd"
        host_dir.mkdir(parents=True)
        (host_dir / "10-enp0s31f6.network").write_text("[Match]\nName=enp0s31f6\n")

    return tmp_path


@pytest.fixture
def render_script(repo_root):
    """Provide path to cli.py script."""
    return repo_root / "tools" / "render" / "cli.py"


@pytest.fixture
def apply_script(repo_root):
    """Provide path to apply.sh script."""
    return repo_root / "tools" / "apply" / "apply.sh"


@pytest.fixture(scope="session")
def skip_desec_env():
    """Provide environment variables that skip deSEC checks."""
    import os

    env = os.environ.copy()
    env["SKIP_DESEC"] = "1"
    return env


# --- Activity 5: Additional integration test fixtures ---


@pytest.fixture
def mock_vault_setup(tmp_path):
    """Create mock Vault setup for testing secret rendering."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    # Mock Vault config
    vault_config = {
        "address": "http://127.0.0.1:8200",
        "token": "mock-token-12345",
    }

    config_file = vault_dir / "config.json"
    import json

    config_file.write_text(json.dumps(vault_config))

    return {
        "vault_dir": vault_dir,
        "config_file": config_file,
        "address": vault_config["address"],
        "token": vault_config["token"],
    }


@pytest.fixture
def mock_desec_api(monkeypatch):
    """Mock deSEC API responses for testing DNS plan generation."""

    class MockDesecResponse:
        def __init__(self, records):
            self.records = records

        def json(self):
            return self.records

        @property
        def status_code(self):
            return 200

    mock_records = [
        {"name": "@", "type": "A", "content": ["1.2.3.4"]},
        {"name": "www", "type": "A", "content": ["1.2.3.5"]},
    ]

    def mock_get(*args, **kwargs):
        return MockDesecResponse(mock_records)

    monkeypatch.setattr("requests.get", mock_get)

    return mock_records


@pytest.fixture
def temporary_rendered_dirs(tmp_path):
    """Create temporary directory structure for rendered configs."""
    rendered_base = tmp_path / "rendered"
    rendered_base.mkdir()

    hosts = ["phobos", "deimos"]
    for host in hosts:
        host_dir = rendered_base / host
        host_dir.mkdir()

        # Create standard subdirs
        (host_dir / "systemd-networkd").mkdir()
        (host_dir / "services").mkdir()
        (host_dir / "systemd").mkdir()

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    return {
        "rendered_base": rendered_base,
        "state_dir": state_dir,
        "hosts": {host: rendered_base / host for host in hosts},
    }
