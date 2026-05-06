"""Tests for quadlet rendering error paths."""

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.errors import RenderError


def test_missing_template_raises(tmp_path: Path, write_file: Any) -> None:
    """Missing volume template raises RenderError."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "output" / "services"

    write_file(
        config_root / "services" / "vault" / "service.yaml",
        "name: vault\n"
        "podman:\n"
        "  user: root\n"
        "  network: ipvlan-l2\n"
        "composition:\n"
        "  container:\n"
        "    named_volumes:\n"
        "      - name: config\n"
        "        host_path: /srv/vault/config\n"
        "        mount_path: /vault/config\n"
        "    mounted_files: []\n",
    )

    (config_root / "services" / "vault" / "quadlets").mkdir(parents=True, exist_ok=True)

    network: dict[str, Any] = {
        "vlans": {"services": {"cidr": "172.20.20.0/24"}},
        "services": {"vault": {"vlan": "services", "address": "172.20.20.100/32"}},
    }

    with pytest.raises(RenderError, match="Missing volume template"):
        render_service_quadlets(
            "phobos",
            ["vault"],
            network,
            config_root,
            output_dir,
        )


def test_invalid_volume_definition(tmp_path: Path, write_file: Any) -> None:
    """Invalid named volume entries raise RenderError."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "output" / "services"

    write_file(
        config_root / "services" / "svc-broken" / "service.yaml",
        "name: svc-broken\n"
        "podman:\n"
        "  user: root\n"
        "  network: ipvlan-l2\n"
        "composition:\n"
        "  container:\n"
        "    named_volumes:\n"
        "      - name: config\n"
        "        host_path: /srv/config\n"
        "        # mount_path is missing\n"
        "    mounted_files: []\n",
    )

    write_file(
        config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
        "[Volume]\nDevice={{ host_path }}\n",
    )
    (config_root / "services" / "svc-broken" / "quadlets").mkdir(parents=True, exist_ok=True)

    network: dict[str, Any] = {
        "vlans": {"services": {"cidr": "172.20.20.0/24"}},
        "services": {"svc-broken": {"vlan": "services", "address": "172.20.20.101/32"}},
    }

    with pytest.raises(RenderError, match="Invalid named volume for service 'svc-broken'"):
        render_service_quadlets(
            "phobos",
            ["svc-broken"],
            network,
            config_root,
            output_dir,
        )
