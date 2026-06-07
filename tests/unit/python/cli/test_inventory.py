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

    def test_markdown_format_with_network_data(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--format markdown renders VLAN table, hosts, services, addresses, DNS zones."""
        config_root = tmp_path / "config"
        _write_mapping(config_root, {"abhaile": [{"phobos": ["blocky", "vault"]}]})
        _write_service(config_root, "blocky")
        _write_service(config_root, "vault")

        network = {
            "vlans": {
                "services": {
                    "id": 20,
                    "cidr": "172.20.20.0/24",
                    "gateway": "172.20.20.1",
                    "ipvlanl2_range": "172.20.20.200-172.20.20.254",
                }
            },
            "hosts": {
                "phobos": {
                    "interfaces": {"enp0s31f6": {"address": "172.20.20.10/24", "vlan": "services"}}
                }
            },
            "services": {
                "blocky": {"address": "172.20.20.234/32", "vlan": "services", "dns": []},
                "vault": {"address": "172.20.20.204/32", "vlan": "services", "dns": []},
            },
            "dns": {
                "zones": [
                    {
                        "name": "svc.abhaile.home.arpa.",
                        "provider": {"type": "internal", "name": "coredns-common"},
                    },
                ]
            },
        }
        (config_root / "network.yaml").write_text(yaml.dump(network))

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        rc = main_inventory(["--format", "markdown"])
        output = capsys.readouterr().out
        assert rc == 0
        assert "## VLAN Summary" in output
        assert "| services |" in output
        assert "## Hosts" in output
        assert "enp0s31f6" in output
        assert "## Services by Host" in output
        assert "blocky" in output
        assert "## Address Allocation" in output
        assert "172.20.20.204/32" in output
        assert "## DNS Zones" in output
        assert "svc.abhaile.home.arpa." in output

    def test_markdown_output_to_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--output writes markdown to file instead of stdout."""
        config_root = tmp_path / "config"
        _write_mapping(config_root, {"abhaile": [{"phobos": ["svc-a"]}]})
        _write_service(config_root, "svc-a")

        monkeypatch.setattr("abhaile.cli.inventory.get_repo_root", lambda _: tmp_path)
        monkeypatch.setattr(
            "abhaile.cli.inventory.load_paths",
            lambda _: {"config_root": "config"},
        )

        out_file = tmp_path / "out" / "inventory.md"
        rc = main_inventory(["--format", "markdown", "--output", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "# Abhaile Infrastructure Inventory" in content


class TestInventoryHelpers:
    """Tests for inventory helper functions."""

    def test_ip_sort_key_orders_correctly(self) -> None:
        """_ip_sort_key should sort IPs numerically."""
        from abhaile.cli.inventory import _ip_sort_key

        addrs = ["172.20.20.234/32", "172.20.20.10/24", "172.20.20.204/32"]
        sorted_addrs = sorted(addrs, key=_ip_sort_key)
        assert sorted_addrs == ["172.20.20.10/24", "172.20.20.204/32", "172.20.20.234/32"]

    def test_service_network_mode_reads_from_service_yaml(self, tmp_path: Path) -> None:
        """_service_network_mode extracts podman.network from service.yaml."""
        from abhaile.cli.inventory import _service_network_mode

        svc_dir = tmp_path / "services" / "blocky"
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(
            "name: blocky\npodman:\n  user: root\n  network: ipvlan-l2\n"
        )

        assert _service_network_mode("blocky", tmp_path) == "ipvlan-l2"

    def test_service_network_mode_missing_service(self, tmp_path: Path) -> None:
        """_service_network_mode returns 'unknown' for missing service."""
        from abhaile.cli.inventory import _service_network_mode

        assert _service_network_mode("nonexistent", tmp_path) == "unknown"
