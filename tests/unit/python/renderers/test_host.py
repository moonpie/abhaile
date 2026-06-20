"""Unit tests for host configuration renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.host import render_host_config


class TestRenderHostConfig:
    """Tests for render_host_config()."""

    def test_renders_resolved_conf_from_common(self, tmp_path: Path, write_file: Any) -> None:
        """Common resolved.conf entry is rendered to output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(
            config_root / "hosts" / "common" / "resolved.conf",
            "[Resolve]\nDNS=172.20.20.234\n",
        )

        common_config = {
            "composition": {
                "config": [
                    {
                        "source": "common/resolved.conf",
                        "destination": "/etc/systemd/resolved.conf",
                    }
                ]
            }
        }
        host_config: dict[str, Any] = {"composition": {"config": []}}

        render_host_config("phobos", host_config, common_config, {}, config_root, output_dir)

        assert (output_dir / "etc/systemd/resolved.conf").exists()
        assert "DNS=172.20.20.234" in (output_dir / "etc/systemd/resolved.conf").read_text()

    def test_excludes_networkd_entries(self, tmp_path: Path, write_file: Any) -> None:
        """Entries under /etc/systemd/network/ are excluded (handled by networkd renderer)."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(config_root / "hosts" / "phobos" / "eth0.network", "[Match]\nName=eth0\n")

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "phobos/eth0.network",
                        "destination": "/etc/systemd/network/10-eth0.network",
                    }
                ]
            }
        }
        common_config: dict[str, Any] = {"composition": {"config": []}}

        render_host_config("phobos", host_config, common_config, {}, config_root, output_dir)

        assert not (output_dir / "etc/systemd/network/10-eth0.network").exists()

    def test_registers_artifacts_with_collector(self, tmp_path: Path, write_file: Any) -> None:
        """Rendered files are registered with the artifact collector."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "output"
        collector = ArtifactCollector()

        write_file(
            config_root / "hosts" / "common" / "resolved.conf",
            "[Resolve]\nDNS=8.8.8.8\n",
        )

        common_config = {
            "composition": {
                "config": [
                    {
                        "source": "common/resolved.conf",
                        "destination": "/etc/systemd/resolved.conf",
                    }
                ]
            }
        }
        host_config: dict[str, Any] = {"composition": {"config": []}}

        render_host_config(
            "phobos",
            host_config,
            common_config,
            {},
            config_root,
            rendered_root,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = collector.get_all_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0].target_path == "/etc/systemd/resolved.conf"
        assert artifacts[0].owner_ref == "service:systemd-resolved"
        assert artifacts[0].kind == "resolved.config"

    def test_host_entries_override_common(self, tmp_path: Path, write_file: Any) -> None:
        """Host-specific entries are rendered after common."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(config_root / "hosts" / "common" / "ntp.conf", "server pool.ntp.org\n")
        write_file(config_root / "hosts" / "phobos" / "ntp.conf", "server local.ntp\n")

        common_config = {
            "composition": {
                "config": [{"source": "common/ntp.conf", "destination": "/etc/chrony/chrony.conf"}]
            }
        }
        host_config = {
            "composition": {
                "config": [{"source": "phobos/ntp.conf", "destination": "/etc/chrony/chrony.conf"}]
            }
        }

        render_host_config("phobos", host_config, common_config, {}, config_root, output_dir)

        content = (output_dir / "etc/chrony/chrony.conf").read_text()
        assert "server local.ntp" in content

    def test_renders_host_systemd_entries_with_apply_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Host composition.systemd entries render with systemd metadata."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "output"
        collector = ArtifactCollector()

        write_file(
            config_root / "hosts" / "common" / "systemd" / "demo.service",
            "[Service]\nType=oneshot\n",
        )
        common_config = {
            "composition": {
                "config": [],
                "systemd": [
                    {
                        "source": "common/systemd/demo.service",
                        "destination": "/etc/systemd/system/demo.service",
                        "enable": True,
                        "start": True,
                    }
                ],
            }
        }
        host_config: dict[str, Any] = {"composition": {"config": [], "systemd": []}}

        render_host_config(
            "phobos",
            host_config,
            common_config,
            {},
            config_root,
            rendered_root,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifact = collector.get_all_artifacts()[0]
        assert artifact.target_path == "/etc/systemd/system/demo.service"
        assert artifact.kind == "systemd.unit"
        assert artifact.owner_ref == "unit:demo.service"
        assert artifact.apply_hints == {
            "enable_mode": "enable",
            "activation_mode": "start",
        }

    def test_host_systemd_templates_receive_host_services(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Host systemd templates receive mapped host services."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(
            config_root / "hosts" / "common" / "systemd" / "demo.service.j2",
            'After={% if "vault" in host_services %}vault.service {% endif %}'
            "network-online.target\n"
            "Vault={{ vault_addr | strip_cidr }}\n",
        )
        common_config = {
            "composition": {
                "config": [],
                "systemd": [
                    {
                        "source": {
                            "template": "common/systemd/demo.service.j2",
                            "variables": {
                                "vault_addr": "%%network.services.vault.address%%",
                            },
                        },
                        "destination": "/etc/systemd/system/demo.service",
                    }
                ],
            }
        }
        host_config: dict[str, Any] = {"composition": {"config": [], "systemd": []}}
        network = {"services": {"vault": {"address": "172.20.20.204/32"}}}

        render_host_config(
            "phobos",
            host_config,
            common_config,
            network,
            config_root,
            output_dir,
            host_services=["vault", "vault-agent"],
        )

        content = (output_dir / "etc/systemd/system/demo.service").read_text()
        assert "After=vault.service network-online.target" in content
        assert "Vault=172.20.20.204" in content

    def test_host_systemd_dropins_do_not_receive_lifecycle_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Host systemd drop-ins do not receive independent enable/start hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "output"
        collector = ArtifactCollector()

        write_file(
            config_root / "hosts" / "common" / "systemd" / "demo.conf",
            "[Service]\nEnvironment=DEMO=1\n",
        )
        common_config = {
            "composition": {
                "config": [],
                "systemd": [
                    {
                        "source": "common/systemd/demo.conf",
                        "destination": "/etc/systemd/system/demo.service.d/override.conf",
                        "enable": True,
                        "start": True,
                    }
                ],
            }
        }
        host_config: dict[str, Any] = {"composition": {"config": [], "systemd": []}}

        render_host_config(
            "phobos",
            host_config,
            common_config,
            {},
            config_root,
            rendered_root,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifact = collector.get_all_artifacts()[0]
        assert artifact.kind == "systemd.dropin"
        assert artifact.owner_ref == "unit:demo.service"
        assert artifact.apply_hints is None
