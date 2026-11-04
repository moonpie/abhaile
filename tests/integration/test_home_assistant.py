"""Verify Home Assistant deployment preserves application-managed state."""

from pathlib import Path

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.ingress import render_ingress_configs
from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.renderers.services import render_service_configs
from abhaile.utils.config import read_json, read_yaml
from abhaile.validation.schema import validate_schema

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]


def test_home_assistant_preserves_configuration_and_uses_isolated_network(tmp_path: Path) -> None:
    config = REPO / "config"
    schema = REPO / "schemas/service.schema.json"
    definition = read_yaml(config / "services/home-assistant/service.yaml")
    validate_schema(definition, read_json(schema), "home-assistant/service.yaml", schema)
    network = read_yaml(config / "network.yaml")
    collector = ArtifactCollector()
    for renderer in (render_service_configs, render_service_quadlets):
        renderer(
            "phobos",
            ["home-assistant"],
            network,
            config,
            tmp_path / "services",
            collector=collector,
            rendered_root=tmp_path,
        )
    quadlet = (
        tmp_path / "services/home-assistant/etc/containers/systemd/home-assistant.container"
    ).read_text()
    assert "Image=ghcr.io/home-assistant/home-assistant:2026.11.0" in quadlet
    assert "Network=services.network" in quadlet
    assert "--ip=172.20.20.221" in quadlet
    assert "--umask=0077" in quadlet
    assert "After=network-online.target mosquitto.service abhaile-secrets-ready.service" in quadlet
    assert "Requires=mosquitto.service" not in quadlet
    assert "StopTimeout=300" in quadlet and "TimeoutStopSec=330s" in quadlet
    for unsupported in ("Privileged=", "AddDevice=", "PublishPort=", "Network=host", "/run/dbus"):
        assert unsupported not in quadlet
    artifacts = {entry.target_path: entry for entry in collector.get_all_artifacts()}
    assert artifacts["/srv/home-assistant/config"].apply_hints == {
        "owner": "root",
        "group": "root",
        "mode": "0750",
    }
    assert not any(
        path.startswith("/srv/home-assistant/config/") for path in artifacts
    ), "Application configuration and credentials must remain application-owned"


def test_home_assistant_ingress_preserves_native_authentication(tmp_path: Path) -> None:
    render_ingress_configs(
        "phobos",
        ["caddy-internal", "home-assistant"],
        ["caddy-internal", "home-assistant"],
        REPO / "config",
        tmp_path,
    )
    rendered = (tmp_path / "caddy-internal/srv/caddy/internal/Caddyfile").read_text()
    site = rendered.split("home-assistant.abhaile.home.arpa {", 1)[1].split("\n}", 1)[0]
    assert "import tls_internal" in site
    assert "reverse_proxy http://home-assistant.svc.abhaile.home.arpa:8123" in site
    assert "authelia_forward_auth" not in site
    assert "common_headers" not in site
    assert "header_up" not in site
