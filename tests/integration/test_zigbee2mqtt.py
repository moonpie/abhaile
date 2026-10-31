"""Verify protected Zigbee2MQTT deployment without owning mutable application files."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.renderers.services import render_service_configs
from abhaile.renderers.vault_templates.rendering import render_vault_agent_configs
from abhaile.utils.config import read_json, read_yaml
from abhaile.validation.schema import validate_schema

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]


def test_zigbee2mqtt_preserves_mutable_configuration_and_orders_secure_startup(
    tmp_path: Path,
) -> None:
    config = REPO / "config"
    schema = REPO / "schemas/service.schema.json"
    definition = read_yaml(config / "services/zigbee2mqtt/service.yaml")
    validate_schema(definition, read_json(schema), "zigbee2mqtt/service.yaml", schema)
    network = read_yaml(config / "network.yaml")
    collector = ArtifactCollector()
    for renderer in (render_service_configs, render_service_quadlets):
        renderer(
            "phobos",
            ["zigbee2mqtt"],
            network,
            config,
            tmp_path / "services",
            collector=collector,
            rendered_root=tmp_path,
        )
    directory = tmp_path / "services/zigbee2mqtt"
    quadlet = (directory / "etc/containers/systemd/zigbee2mqtt.container").read_text()
    assert "Image=ghcr.io/koenkk/zigbee2mqtt:2.14.2" in quadlet
    assert "--ip=172.20.20.223" in quadlet
    assert "--umask=0077" in quadlet
    assert "Environment=Z2M_ONBOARD_NO_SERVER=1" in quadlet
    assert "ZIGBEE2MQTT_CONFIG_SERIAL_PORT=tcp://172.20.50.10:6638" in quadlet
    assert "ZIGBEE2MQTT_CONFIG_SERIAL_ADAPTER=zstack" in quadlet
    assert "mqtt://172.20.20.222:1883" in quadlet
    assert "ZIGBEE2MQTT_CONFIG_FRONTEND_ENABLED=true" in quadlet
    assert "ZIGBEE2MQTT_CONFIG_HOMEASSISTANT_ENABLED=false" in quadlet
    assert "Requires=abhaile-secrets-ready.service zigbee2mqtt-env.service" in quadlet
    assert "Requires=mosquitto.service" not in quadlet
    assert "PublishPort=" not in quadlet and "AddDevice=" not in quadlet
    assert "Notify=healthy" in quadlet
    health_command = next(
        line.split("=", 1)[1] for line in quadlet.splitlines() if line.startswith("HealthCmd=")
    )
    command = shlex.split(health_command)
    assert command[:2] == ["node", "-e"]
    assert len(command) == 3
    assert "Frontend HTTP status:" in command[2]
    assert "Frontend request failed:" in command[2]
    assert "e.cause?.code" in command[2]
    assert "HealthLogDestination=events_logger" in quadlet
    assert "HealthTimeout=5s" in quadlet
    assert "TimeoutStartSec=240s" in quadlet
    artifacts = {entry.target_path: entry for entry in collector.get_all_artifacts()}
    assert "/srv/zigbee2mqtt/data/configuration.yaml" not in artifacts
    assert artifacts["/srv/zigbee2mqtt/data"].apply_hints == {
        "owner": "root",
        "group": "root",
        "mode": "0750",
    }
    refresh = (directory / "etc/systemd/system/zigbee2mqtt-env.service").read_text()
    assert "install -m 0600" in refresh
    assert "cmp -s" in refresh
    assert "--no-block try-restart zigbee2mqtt.service" in refresh


def test_zigbee2mqtt_credentials_use_existing_mqtt_identity_and_separate_frontend_secret(
    tmp_path: Path,
) -> None:
    collector = ArtifactCollector()
    render_vault_agent_configs(
        "phobos",
        ["vault-agent", "zigbee2mqtt"],
        read_yaml(REPO / "config/network.yaml"),
        REPO / "config",
        tmp_path / "services",
        collector=collector,
        rendered_root=tmp_path,
    )
    template = (
        tmp_path / "services/vault-agent/srv/vault/agent/templates/zigbee2mqtt.env.ctmpl"
    ).read_text()
    assert 'secret "secret/data/abhaile/mqtt"' in template
    assert 'secret "secret/data/abhaile/zigbee2mqtt"' in template
    # Podman preserves quotes and backslashes in env files, unlike systemd.
    assignments = [line for line in template.splitlines() if line.startswith("ZIGBEE2MQTT_")]
    assert assignments == [
        "ZIGBEE2MQTT_CONFIG_MQTT_USER={{ .Data.data.zigbee2mqtt_username }}",
        "ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD={{ .Data.data.zigbee2mqtt_password }}",
        "ZIGBEE2MQTT_CONFIG_FRONTEND_AUTH_TOKEN={{ .Data.data.frontend_auth_token }}",
    ]
    assert "home_assistant_password" not in template and "frigate_password" not in template
    rendered_config = next(
        entry for entry in collector.get_all_artifacts() if entry.kind == "vault.config"
    )
    assert (
        "/srv/vault/agent/out/zigbee2mqtt.env"
        in (rendered_config.apply_hints or {})["required_outputs"]
    )


def test_zigbee2mqtt_ingress_has_sso_and_matching_restrictive_policy() -> None:
    ingress = (REPO / "config/services/zigbee2mqtt/caddy/internal-ingress.txt").read_text()
    assert "import authelia_forward_auth" in ingress
    assert "zigbee2mqtt.svc.abhaile.home.arpa:8080" in ingress
    auth = (
        REPO / "config/services/authelia/templates/authelia.configuration.yml.ctmpl"
    ).read_text()
    rule = auth.split("- domain: zigbee2mqtt.abhaile.home.arpa", 1)[1]
    assert "policy: one_factor" in rule and "group:admins" in rule


def test_zigbee2mqtt_health_command_survives_native_quadlet_generation(tmp_path: Path) -> None:
    generator = Path("/usr/libexec/podman/quadlet")
    if not generator.is_file():
        pytest.skip("Native Quadlet generator is unavailable")
    render_service_quadlets(
        "phobos",
        ["zigbee2mqtt"],
        read_yaml(REPO / "config/network.yaml"),
        REPO / "config",
        tmp_path / "services",
    )
    rendered = (
        tmp_path / "services/zigbee2mqtt/etc/containers/systemd/zigbee2mqtt.container"
    ).read_text()
    probe = next(line for line in rendered.splitlines() if line.startswith("HealthCmd="))
    # Podman 5.4's UnitFile.Lookup trims double quotes at either end.
    # Local generator versions differ, so check that target behavior explicitly.
    target_value = probe.split("=", 1)[1].rstrip().strip('"')
    subprocess.run(["/bin/sh", "-n", "-c", target_value], check=True, capture_output=True)
    assert len(shlex.split(target_value)) == 3
    # Isolate the actual rendered probe from network and volume dependencies.
    units = tmp_path / "quadlets"
    units.mkdir()
    (units / "probe.container").write_text(
        "[Container]\nImage=localhost/probe:latest\n" + probe + "\n"
    )
    generated = subprocess.run(
        [str(generator), "--dryrun"],
        env={**os.environ, "QUADLET_UNIT_DIRS": str(units)},
        capture_output=True,
        text=True,
        check=True,
    )
    unit = generated.stdout + generated.stderr
    exec_start = next(
        line.split("=", 1)[1] for line in unit.splitlines() if line.startswith("ExecStart=")
    )
    arguments = shlex.split(exec_start)
    health = arguments[arguments.index("--health-cmd") + 1]
    # Exercise the generated shell command without starting a container.
    subprocess.run(["/bin/sh", "-n", "-c", health], check=True, capture_output=True)
    command = shlex.split(health)
    assert command[:2] == ["node", "-e"]
    assert len(command) == 3
    assert 'fetch("http://172.20.20.223:8080")' in command[2]
    assert 'console.log("Frontend HTTP status:",r.status)' in command[2]
