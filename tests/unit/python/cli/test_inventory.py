"""Tests for abhaile-inventory CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from abhaile.cli.inventory import main as main_inventory


def _write_mapping(config_root: Path, mapping: dict) -> None:
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "mapping.yaml").write_text(yaml.dump(mapping))


def _write_service(config_root: Path, name: str) -> None:
    svc_dir = config_root / "services" / name
    svc_dir.mkdir(parents=True, exist_ok=True)
    (svc_dir / "service.yaml").write_text(f"name: {name}\n")


class TestInventoryCli:
    """Tests for main_inventory()."""

    def test_human_readable_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Human-readable output lists hosts sorted with services in mapping order."""
        config_root = tmp_path / "config"
        _write_mapping(
            config_root,
            {"abhaile": [{"phobos": ["svc-b", "svc-a"]}, {"deimos": ["svc-c"]}]},
        )
        _write_service(config_root, "svc-a")
        _write_service(config_root, "svc-b")
        _write_service(config_root, "svc-c")

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        rc = main_inventory([])
        output = capsys.readouterr().out
        assert rc == 0
        # deimos comes before phobos (alphabetical)
        assert output.index("deimos:") < output.index("phobos:")
        # services in mapping order for phobos
        assert output.index("svc-b") < output.index("svc-a")

    def test_json_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--json outputs machine-readable JSON with host keys."""
        config_root = tmp_path / "config"
        _write_mapping(
            config_root,
            {"abhaile": [{"phobos": ["svc-a"]}, {"deimos": ["svc-b"]}]},
        )
        _write_service(config_root, "svc-a")
        _write_service(config_root, "svc-b")

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        rc = main_inventory(["--json"])
        output = capsys.readouterr().out
        payload = json.loads(output)
        assert rc == 0
        assert payload["deimos"] == ["svc-b"]
        assert payload["phobos"] == ["svc-a"]

    def test_validate_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--validate exits 0 when all services have definitions."""
        config_root = tmp_path / "config"
        _write_mapping(config_root, {"abhaile": [{"phobos": ["svc-a"]}]})
        _write_service(config_root, "svc-a")

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        rc = main_inventory(["--validate"])
        assert rc == 0

    def test_validate_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--validate exits 1 and reports missing service definitions."""
        config_root = tmp_path / "config"
        _write_mapping(config_root, {"abhaile": [{"phobos": ["missing-svc"]}]})
        # Do NOT create the service definition

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        rc = main_inventory(["--validate"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "missing" in err
