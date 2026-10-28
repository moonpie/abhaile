"""Verify adoption metadata and retired-field rejection with production config and schema."""

from pathlib import Path

import pytest

from abhaile.cli.render import load_and_validate, render_host
from abhaile.utils.config import read_json, read_yaml_mapping
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import load_paths
from abhaile.validation.schema import validate_schema

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", [False, True])
def test_retired_ownership_flag_rejected(value: bool) -> None:
    """Reject both values rather than treating the retired flag as an ignored setting."""
    schema_path = REPO / "schemas/common.schema.json"
    schema = read_json(schema_path)["definitions"]["namedVolume"]
    volume = {
        "name": "data",
        "host_path": "/srv/example/data",
        "mount_path": "/data",
        "host_owner": 0,
        "host_group": 0,
        "manage_host_ownership": value,
    }
    with pytest.raises(RenderError, match="Additional properties are not allowed"):
        validate_schema(volume, schema, "named volume", schema_path)


def test_all_services_validate_without_ownership_opt_out() -> None:
    """Include unmapped service definitions in retired-field validation."""
    schema_path = REPO / "schemas/service.schema.json"
    schema = read_json(schema_path)
    for path in sorted((REPO / "config/services").glob("*/service.yaml")):
        validate_schema(read_yaml_mapping(path), schema, str(path), schema_path)
        assert "manage_host_ownership" not in path.read_text()


def test_inspected_private_roots_are_manifest_managed(tmp_path: Path) -> None:
    """Render the actual host and assert all twelve observed directory identities."""
    paths = load_paths(REPO)
    config = load_and_validate(REPO, paths)
    manifest_path = render_host(
        "phobos", tmp_path, paths, False, REPO, config.mapping, config.network, config.host_services
    )
    manifest = read_json(manifest_path)
    directories = {
        item["target_path"]: item
        for item in manifest["entries"]
        if item["kind"] == "service.directory"
    }
    expected = {
        path: (0, 0)
        for path in [
            "/srv/vault/config",
            "/srv/vault/data",
            "/srv/caddy/internal/config",
            "/srv/caddy/internal/data",
            "/srv/caddy/dmz/config",
            "/srv/caddy/dmz/data",
            "/srv/authelia/authelia/config",
            "/srv/authelia/authelia/data",
            "/srv/omada-controller/omada-controller/cert",
        ]
    }
    expected.update(
        {
            "/srv/authelia/redis/data": (999, 0),
            "/srv/omada-controller/omada-controller/data": (508, 508),
            "/srv/omada-controller/omada-controller/logs": (508, 508),
        }
    )
    for path, (owner, group) in expected.items():
        assert directories[path]["apply_hints"] == {"owner": owner, "group": group, "mode": "0750"}
    assert "/etc/ssl/certs" not in directories
    mosquitto = read_yaml_mapping(REPO / "config/services/mosquitto/service.yaml")
    assert all(
        item.get("destination") != "/srv/mosquitto/config"
        for item in mosquitto["composition"]["config"]
    )
    assert directories["/srv/mosquitto/config"]["apply_hints"] == {
        "owner": "root",
        "group": "root",
        "mode": "0755",
    }
