"""Unit tests for software renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.software import render_software_artifacts
from abhaile.utils.errors import RenderError


def _write_software_schema(repo_root: Path) -> None:
    schema_dir = repo_root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "software-action.schema.json").write_text(
        """
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["id", "name", "commands"],
  "properties": {
    "id": {"type": "string"},
    "name": {"type": "string"},
    "description": {"type": "string"},
    "commands": {
      "type": "array",
      "minItems": 1,
      "items": {"type": "string"}
    }
  },
  "additionalProperties": false
}
""".strip() + "\n",
        encoding="utf-8",
    )


def test_render_software_merges_and_renders_artifacts(write_file: Any, tmp_path: Path) -> None:
    """Merged package list and per-entry specs are rendered for a host."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "software"

    _write_software_schema(tmp_path)

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  software:
    packages:
      - podman
      - curl
    downloads:
      - sops
    builds: []
    commands:
      - systemd-networkd
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  software:
    packages:
      - ddclient
    downloads: []
    builds:
      - gasket-dkms
    commands:
      - ddclient
""".strip() + "\n",
    )

    write_file(
        config_root / "hosts" / "common" / "software" / "downloads" / "sops.yaml",
        """
id: sops
name: Install sops
commands:
  - echo install sops
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "common" / "software" / "commands" / "systemd-networkd.yaml",
        """
id: systemd-networkd
name: Enable networkd
commands:
  - echo networkd
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "software" / "builds" / "gasket-dkms.yaml",
        """
id: gasket-dkms
name: Build gasket
commands:
  - echo build gasket
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "software" / "commands" / "ddclient.yaml",
        """
id: ddclient
name: Enable ddclient
commands:
  - echo enable ddclient
""".strip() + "\n",
    )

    render_software_artifacts("phobos", config_root, output_dir)

    assert (output_dir / "packages.txt").read_text(encoding="utf-8") == "podman\ncurl\nddclient\n"
    assert (output_dir / "downloads" / "sops.yaml").exists()
    assert (output_dir / "builds" / "gasket-dkms.yaml").exists()
    assert (output_dir / "commands" / "systemd-networkd.yaml").exists()
    assert (output_dir / "commands" / "ddclient.yaml").exists()


def test_render_software_errors_on_duplicate_entries(write_file: Any, tmp_path: Path) -> None:
    """Duplicate ids across include chain fail fast."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "software"

    _write_software_schema(tmp_path)

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  software:
    packages:
      - curl
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  software:
    packages:
      - curl
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="Duplicate software packages entry 'curl'"):
        render_software_artifacts("phobos", config_root, output_dir)


def test_render_software_errors_on_missing_spec(write_file: Any, tmp_path: Path) -> None:
    """Missing referenced software spec file fails render."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "software"

    _write_software_schema(tmp_path)

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  software:
    downloads:
      - sops
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  software: {}
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="Missing software downloads spec"):
        render_software_artifacts("phobos", config_root, output_dir)
