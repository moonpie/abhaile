"""Verify the Mosquitto deployment renders protected persistent resources."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import venv

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.manifest import build_manifest
from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.renderers.services import render_service_configs
from abhaile.renderers.vault_templates.rendering import render_vault_agent_configs
from abhaile.utils.config import read_json, read_yaml
from abhaile.validation.schema import validate_schema
from tests.integration.test_ansible_service_config import _run_playbook, _write_playbook

pytestmark = pytest.mark.integration


def test_mosquitto_deployment(tmp_path: Path) -> None:
    """Render the broker, secure startup dependencies, and persistent mount ownership."""
    repo_root = Path(__file__).resolve().parents[2]
    config_root = repo_root / "config"
    data = read_yaml(config_root / "services/mosquitto/service.yaml")
    schema_path = repo_root / "schemas/service.schema.json"
    validate_schema(data, read_json(schema_path), "mosquitto/service.yaml", schema_path)
    network = read_yaml(config_root / "network.yaml")
    collector = ArtifactCollector()
    output_dir = tmp_path / "services"
    render_service_configs(
        "phobos",
        ["mosquitto"],
        network,
        config_root,
        output_dir,
        collector=collector,
        rendered_root=tmp_path,
    )
    render_service_quadlets(
        "phobos",
        ["mosquitto"],
        network,
        config_root,
        output_dir,
        collector=collector,
        rendered_root=tmp_path,
    )
    service_dir = output_dir / "mosquitto"
    broker_config = (service_dir / "srv/mosquitto/config/mosquitto.conf").read_text()
    assert "listener 1883 172.20.20.222" in broker_config
    assert "allow_anonymous false" in broker_config
    assert "password_file /mosquitto/secrets/passwords" in broker_config
    assert "persistence true" in broker_config
    assert "persistence_location /mosquitto/data/" in broker_config
    quadlet = (service_dir / "etc/containers/systemd/mosquitto.container").read_text()
    assert f"Image={data['composition']['container']['image']}" in quadlet
    assert "Network=services.network" in quadlet
    assert "PodmanArgs=--ip=172.20.20.222" in quadlet
    assert "User=1883:1883" in quadlet
    assert "Requires=abhaile-secrets-ready.service mosquitto-passwords.service" in quadlet
    assert "WantedBy=abhaile-secrets-ready.service" in quadlet
    assert "Notify=healthy" in quadlet
    assert "mosquitto_sub -o /dev/null -V mqttv5 -h 172.20.20.222" in quadlet
    assert "test $$? -eq 135" in quadlet
    assert "PublishPort=" not in quadlet
    refresh = (service_dir / "etc/systemd/system/mosquitto-passwords.service").read_text()
    assert f"--image {data['composition']['container']['image']}" in refresh
    assert "-m abhaile.cli.mosquitto_passwords" in refresh
    assert "Environment=PYTHONPATH=/opt/abhaile/src" in refresh
    assert "--source /srv/vault/agent/out/mosquitto-accounts.json" in refresh
    assert "--destination /srv/mosquitto/secrets/passwords" in refresh
    assert not (service_dir / "srv/mosquitto/secrets/passwords").exists()
    artifacts = {artifact.target_path: artifact for artifact in collector.get_all_artifacts()}
    config_directory = artifacts["/srv/mosquitto/config"]
    assert config_directory.kind == "service.directory"
    assert config_directory.is_directory
    assert config_directory.apply_hints is not None
    assert {name: config_directory.apply_hints[name] for name in ("owner", "group", "mode")} == {
        "owner": "root",
        "group": "root",
        "mode": "0755",
    }
    assert artifacts["/srv/mosquitto/data"].apply_hints == {
        "owner": 1883,
        "group": 1883,
        "mode": "0750",
    }
    assert artifacts["/srv/mosquitto/secrets"].apply_hints == {
        "owner": "root",
        "group": 1883,
        "mode": "0750",
    }
    assert artifacts["/srv/mosquitto/config/mosquitto.conf"].apply_hints == {
        "restart_unit": "mosquitto.service",
        "rootless": False,
    }


def test_mosquitto_check_accepts_absent_config_directory(tmp_path: Path) -> None:
    """Check first-install config publication using parents declared by the real manifest."""
    config_root = Path(__file__).resolve().parents[2] / "config"
    rendered_root = tmp_path / "rendered"
    output_dir = rendered_root / "services"
    collector = ArtifactCollector()
    network = read_yaml(config_root / "network.yaml")
    for renderer in (render_service_configs, render_service_quadlets):
        renderer(
            "phobos",
            ["mosquitto"],
            network,
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )
    collector.compute_hashes_and_sizes(rendered_root)
    manifest = build_manifest("phobos", collector.get_metadata())
    live_root = tmp_path / "live"
    entries = [dict(entry) for entry in manifest["entries"] if entry["kind"] == "service.config"]
    for entry in entries:
        entry["target_path"] = str(live_root / entry["target_path"].lstrip("/"))
    parents = [
        live_root / entry["target_path"].lstrip("/")
        for entry in manifest["entries"]
        if entry["kind"] == "service.directory"
    ]
    playbook = _write_playbook(
        tmp_path,
        rendered_root,
        entries,
        managed_directory_targets=parents,
    )
    code, stdout, stderr = _run_playbook(tmp_path / "check", playbook, check=True)
    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert not live_root.exists()


def test_mosquitto_vault_staging_is_scoped_to_phobos(tmp_path: Path) -> None:
    """Collect the shared account template on phobos without mounting staging in the broker."""
    repo_root = Path(__file__).resolve().parents[2]
    config_root = repo_root / "config"
    mapping = read_yaml(config_root / "mapping.yaml")
    network = read_yaml(config_root / "network.yaml")
    host_services = {
        host: services for item in mapping["abhaile"] for host, services in item.items()
    }
    assert "mosquitto" in host_services["phobos"]
    assert "mosquitto" not in host_services["deimos"]
    for host in ("phobos", "deimos"):
        output_dir = tmp_path / host
        render_vault_agent_configs(host, host_services[host], network, config_root, output_dir)
        agent_config = (output_dir / "vault-agent/srv/vault/agent/config.hcl").read_text()
        staging_template = (
            output_dir / "vault-agent/srv/vault/agent/templates/mosquitto-accounts.json.ctmpl"
        )
        if host == "deimos":
            assert "mosquitto-accounts.json" not in agent_config
            assert not staging_template.exists()
            continue
        assert 'destination = "/agent/out/mosquitto-accounts.json"' in agent_config
        assert 'perms       = "0600"' in agent_config
        template = staging_template.read_text()
        assert 'secret "secret/data/abhaile/mqtt"' in template
        for client in ("home_assistant", "zigbee2mqtt", "frigate"):
            assert f".Data.data.{client}_username | toJSON" in template
            assert f".Data.data.{client}_password | toJSON" in template
    definition = read_yaml(config_root / "services/mosquitto/service.yaml")
    mounts = definition["composition"]["container"]["named_volumes"]
    assert all(not mount["host_path"].startswith("/srv/vault/") for mount in mounts)


def test_password_helper_imports_without_installed_package(tmp_path: Path) -> None:
    """Run the unit's module from source in a clean bootstrap-style virtual environment."""
    repo_root = Path(__file__).resolve().parents[2]
    config_root = repo_root / "config"
    output_dir = tmp_path / "rendered"
    render_service_configs(
        "phobos", ["mosquitto"], read_yaml(config_root / "network.yaml"), config_root, output_dir
    )
    unit = (output_dir / "mosquitto/etc/systemd/system/mosquitto-passwords.service").read_text()
    environment_line = next(line for line in unit.splitlines() if line.startswith("Environment="))
    settings = dict(item.split("=", 1) for item in shlex.split(environment_line.split("=", 1)[1]))
    install_root = tmp_path / "install"
    shutil.copytree(
        repo_root / "src", install_root / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    venv.EnvBuilder(with_pip=False).create(install_root / ".venv")
    python = str(install_root / ".venv/bin/python")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [python, "-c", "import importlib.util; assert importlib.util.find_spec('abhaile') is None"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    environment["PYTHONPATH"] = settings["PYTHONPATH"].replace("/opt/abhaile", str(install_root))
    result = subprocess.run(
        [python, "-m", "abhaile.cli.mosquitto_passwords", "--help"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "--source" in result.stdout
    assert "--destination" in result.stdout
