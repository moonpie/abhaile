"""Validate device passthrough against the real schema and Quadlet renderer."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.config import read_json
from abhaile.utils.errors import RenderError
from abhaile.validation.schema import validate_schema

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("in_pod", [False, True], ids=["standalone", "pod"])
@pytest.mark.parametrize(
    "devices",
    [[], ["/dev/apex_0"], ["/dev/apex_0:/dev/apex_0:rw", "/dev/dri/renderD128"]],
)
def test_devices_validate_and_render(tmp_path: Path, in_pod: bool, devices: list[str]) -> None:
    """Accept device lists and emit one AddDevice line per entry in declaration order."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas/service.schema.json"
    container: dict[str, Any] = {"devices": devices}
    composition = (
        {"pod": {"containers": [{"name": "app", "container": container}]}}
        if in_pod
        else {"container": container}
    )
    data = {
        "name": "device-test",
        "podman": {"user": "root", "network": "host", "image": "example.invalid/test:1"},
        "composition": composition,
    }
    validate_schema(data, read_json(schema_path), "service.yaml", schema_path)

    config_root = tmp_path / "config"
    service_dir = config_root / "services/device-test"
    quadlets_dir = service_dir / "quadlets"
    template_dir = quadlets_dir / "app" if in_pod else quadlets_dir
    template_dir.mkdir(parents=True)
    (service_dir / "service.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    if in_pod:
        (quadlets_dir / "pod.pod.j2").write_text("[Pod]\n", encoding="utf-8")
    (template_dir / "container.container.j2").write_text(
        "[Container]\nImage={{ image }}\n"
        "{% for line in device_lines %}\n{{ line }}\n{% endfor %}\n",
        encoding="utf-8",
    )

    filename = "device-test-app-app.container" if in_pod else "device-test.container"
    outputs = []
    for name in ("first", "second"):
        output_dir = tmp_path / name
        render_service_quadlets("phobos", ["device-test"], {}, config_root, output_dir)
        rendered = (output_dir / "device-test/etc/containers/systemd" / filename).read_text()
        assert [line for line in rendered.splitlines() if line.startswith("AddDevice=")] == [
            f"AddDevice={device}" for device in devices
        ]
        outputs.append(rendered)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("in_pod", [False, True], ids=["standalone", "pod"])
@pytest.mark.parametrize("devices", [None, "/dev/apex_0", {}, [""], [None], [42], [{}]])
def test_schema_rejects_invalid_devices(in_pod: bool, devices: Any) -> None:
    """Reject non-list values and entries that are not non-empty strings."""
    schema_path = Path(__file__).resolve().parents[2] / "schemas/service.schema.json"
    container = {"devices": devices}
    composition = (
        {"pod": {"containers": [{"name": "app", "container": container}]}}
        if in_pod
        else {"container": container}
    )
    with pytest.raises(RenderError, match="devices"):
        validate_schema(
            {"name": "device-test", "composition": composition},
            read_json(schema_path),
            "service.yaml",
            schema_path,
        )
