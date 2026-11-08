"""Validate declarative binaries with the production schema and renderer."""

import hashlib
import json
from pathlib import Path
import shutil

import jsonschema
import pytest
import yaml

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.software import render_software_artifacts
from abhaile.utils.errors import RenderError
from abhaile.utils.config import clear_config_cache

REPO = Path(__file__).resolve().parents[2]


def _spec() -> dict:
    """Build a pinned standalone download declaration."""
    return {
        "id": "example",
        "name": "Example binary",
        "binary": {
            "url": "https://example.invalid/releases/v1/example",
            "sha256": "a" * 64,
            "destination": "/usr/local/bin/example",
            "owner_user": "root",
            "owner_group": "root",
            "mode": "0755",
        },
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "http://example.invalid/bin"),
        ("url", "https://user:password@example.invalid/bin"),
        ("sha256", "bad"),
        ("destination", "/usr/bin/example"),
        ("destination", "/usr/local/bin/../example"),
        ("mode", "0777"),
        ("owner_user", "other"),
    ],
)
def test_binary_schema_rejects_unsafe_declarations(field: str, value: str) -> None:
    """Reject acquisition and destination forms outside the bounded family."""
    schema = json.loads((REPO / "schemas/software-action.schema.json").read_text())
    spec = _spec()
    spec["binary"][field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, schema)


@pytest.mark.integration
def test_binary_render_is_deterministic_and_distinguishes_payload(tmp_path: Path) -> None:
    """Render a managed declaration while legacy command lists remain inert."""
    config = tmp_path / "config"
    host = config / "hosts/test"
    downloads = host / "software/downloads"
    downloads.mkdir(parents=True)
    (tmp_path / "schemas").mkdir()
    shutil.copy(REPO / "schemas/software-action.schema.json", tmp_path / "schemas")
    (host / "host.yaml").write_text(
        yaml.safe_dump({"composition": {"software": {"downloads": ["example", "legacy"]}}})
    )
    declaration = _spec()
    (downloads / "example.yaml").write_text(yaml.safe_dump(declaration))
    (downloads / "legacy.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "legacy",
                "name": "Legacy",
                "commands": ["never execute this"],
            }
        )
    )
    root = tmp_path / "rendered"
    snapshots = []
    for _ in range(2):
        collector = ArtifactCollector()
        render_software_artifacts(
            "test", config, root / "software", collector=collector, rendered_root=root
        )
        collector.compute_hashes_and_sizes(root)
        artifacts = collector.get_metadata().artifacts
        binary = artifacts["software/downloads/example.yaml"]
        assert binary.kind == "host.binary"
        assert binary.target_path == "/usr/local/bin/example"
        assert binary.apply_hints is not None
        assert binary.apply_hints["payload_sha256"] == "a" * 64
        assert binary.hash == hashlib.sha256((root / binary.render_path).read_bytes()).hexdigest()
        assert len(artifacts) == 2  # Packages and binary; legacy commands are not managed.
        snapshots.append(binary)
    assert snapshots[0] == snapshots[1]
    declaration["commands"] = ["mixed form"]
    (downloads / "example.yaml").write_text(yaml.safe_dump(declaration))
    clear_config_cache()
    with pytest.raises(RenderError):
        render_software_artifacts("test", config, root / "software")
    declaration.pop("commands")
    builds = host / "software/builds"
    builds.mkdir()
    (builds / "example.yaml").write_text(yaml.safe_dump(declaration))
    (host / "host.yaml").write_text(
        yaml.safe_dump({"composition": {"software": {"builds": ["example"]}}})
    )
    clear_config_cache()
    with pytest.raises(RenderError, match="only in downloads"):
        render_software_artifacts("test", config, root / "software")
