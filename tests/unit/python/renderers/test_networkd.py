"""Unit tests for systemd-networkd renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.networkd import (
    render_networkd_config,
    render_networkd_dropins,
)
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError


class TestRenderNetworkdConfig:
    """Tests for render_networkd_config()."""

    def test_render_static_files(self, tmp_path: Path, write_file: Any) -> None:
        """Static files under /etc/systemd/network/ are copied to output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        # Create source file
        write_file(
            config_root / "hosts" / "phobos" / "networkd" / "10-eth0.network",
            "[Match]\nName=eth0\n",
        )

        # Create host config with static file entry
        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "phobos/networkd/10-eth0.network",
                        "destination": "/etc/systemd/network/10-eth0.network",
                    }
                ]
            }
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            {},
            config_root,
            output_dir,
        )

        output_file = output_dir / "etc/systemd/network/10-eth0.network"
        assert output_file.exists()
        assert output_file.read_text() == "[Match]\nName=eth0\n"

    def test_render_templated_files(self, tmp_path: Path, write_file: Any) -> None:
        """Templated files are rendered with context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        # Create template file
        write_file(
            config_root / "hosts" / "common" / "template.j2",
            "[Resolve]\nDNS={{ dns_server }}\n",
        )

        # Create host config with template entry
        host_config = {
            "composition": {
                "config": [
                    {
                        "source": {
                            "template": "common/template.j2",
                            "variables": {"dns_server": "172.20.20.1"},
                        },
                        "destination": "/etc/systemd/network/resolved.conf",
                    }
                ]
            }
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            {"example": "data"},
            config_root,
            output_dir,
        )

        output_file = output_dir / "etc/systemd/network/resolved.conf"
        assert output_file.exists()
        assert output_file.read_text() == "[Resolve]\nDNS=172.20.20.1\n"

    def test_render_directories(self, tmp_path: Path) -> None:
        """Directories are created with no source entry."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        host_config = {
            "composition": {"config": [{"destination": "/etc/systemd/network/20-vlan.network.d/"}]}
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            {},
            config_root,
            output_dir,
        )

        output_dir_path = output_dir / "etc/systemd/network/20-vlan.network.d"
        assert output_dir_path.is_dir()

    def test_filters_networkd_entries_only(self, tmp_path: Path, write_file: Any) -> None:
        """Only entries with /etc/systemd/network/ destination are processed."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        # Create files for both networkd and resolved
        write_file(
            config_root / "hosts" / "common" / "10-eth0.network",
            "[Match]\nName=eth0\n",
        )
        write_file(
            config_root / "hosts" / "common" / "resolved.conf",
            "[Resolve]\nDNS=8.8.8.8\n",
        )

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "common/10-eth0.network",
                        "destination": "/etc/systemd/network/10-eth0.network",
                    },
                    {
                        "source": "common/resolved.conf",
                        "destination": "/etc/systemd/resolved.conf",
                    },
                ]
            }
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            {},
            config_root,
            output_dir,
        )

        # Only networkd file should be rendered
        assert (output_dir / "etc/systemd/network/10-eth0.network").exists()
        assert not (output_dir / "etc/systemd/resolved.conf").exists()

    def test_common_and_host_configs_merged(self, tmp_path: Path, write_file: Any) -> None:
        """Common and host-specific configs are both rendered."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(
            config_root / "hosts" / "common" / "common.network",
            "[Match]\nName=eth0\n",
        )
        write_file(
            config_root / "hosts" / "phobos" / "phobos.network",
            "[Match]\nName=eth1\n",
        )

        common_config = {
            "composition": {
                "config": [
                    {
                        "source": "common/common.network",
                        "destination": "/etc/systemd/network/common.network",
                    }
                ]
            }
        }

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "phobos/phobos.network",
                        "destination": "/etc/systemd/network/phobos.network",
                    }
                ]
            }
        }

        render_networkd_config("phobos", host_config, common_config, {}, config_root, output_dir)

        assert (output_dir / "etc/systemd/network/common.network").exists()
        assert (output_dir / "etc/systemd/network/phobos.network").exists()

    def test_missing_source_file_raises(self, tmp_path: Path) -> None:
        """RenderError raised if source file doesn't exist."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "phobos/missing.network",
                        "destination": "/etc/systemd/network/missing.network",
                    }
                ]
            }
        }

        with pytest.raises(RenderError, match="Source file not found"):
            render_networkd_config(
                "phobos",
                host_config,
                {"composition": {"config": []}},
                {},
                config_root,
                output_dir,
            )

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        """RenderError raised if template file doesn't exist."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": {
                            "template": "missing.j2",
                            "variables": {},
                        },
                        "destination": "/etc/systemd/network/missing.conf",
                    }
                ]
            }
        }

        with pytest.raises(RenderError, match="Failed to render template"):
            render_networkd_config(
                "phobos",
                host_config,
                {"composition": {"config": []}},
                {},
                config_root,
                output_dir,
            )

    def test_registers_iface_owner_dependencies(self, tmp_path: Path, write_file: Any) -> None:
        """Networkd artifacts register iface owners with dotted-interface dependencies."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"
        collector = ArtifactCollector()

        write_file(
            config_root / "hosts" / "phobos" / "networkd" / "10-enp0s31f6.100.network",
            "[Match]\nName=enp0s31f6.100\n",
        )

        host_config = {
            "composition": {
                "config": [
                    {
                        "source": "phobos/networkd/10-enp0s31f6.100.network",
                        "destination": "/etc/systemd/network/10-enp0s31f6.100.network",
                    }
                ]
            }
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=output_dir,
        )

        owners = collector.get_all_owners()
        assert "iface:enp0s31f6.100" in owners
        assert owners["iface:enp0s31f6.100"].requires == ["iface:enp0s31f6"]

    def test_registers_ipvlan_iface_owner_dependencies(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Networkd artifacts register ipvlan owners with physical/vlan dependencies."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"
        collector = ArtifactCollector()

        write_file(
            config_root / "hosts" / "phobos" / "networkd" / "20-ipvlan-l2.netdev",
            "[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n",
        )
        write_file(
            config_root / "hosts" / "phobos" / "networkd" / "40-ipvlan-l2.100.netdev",
            "[NetDev]\nName=ipvlan-l2.100\nKind=ipvlan\n",
        )

        host_config = {
            "physical_device": "enp0s31f6",
            "composition": {
                "config": [
                    {
                        "source": "phobos/networkd/20-ipvlan-l2.netdev",
                        "destination": "/etc/systemd/network/20-ipvlan-l2.netdev",
                    },
                    {
                        "source": "phobos/networkd/40-ipvlan-l2.100.netdev",
                        "destination": "/etc/systemd/network/40-ipvlan-l2.100.netdev",
                    },
                ]
            },
        }

        network = {
            "hosts": {
                "phobos": {
                    "interfaces": {
                        "enp0s31f6": {"vlan": "services"},
                        "enp0s31f6.100": {"vlan": "dmz"},
                        "ipvlan-l2": {"vlan": "services"},
                        "ipvlan-l2.100": {"vlan": "dmz"},
                    }
                }
            }
        }

        render_networkd_config(
            "phobos",
            host_config,
            {"composition": {"config": []}},
            network,
            config_root,
            output_dir,
            collector=collector,
            rendered_root=output_dir,
        )

        owners = collector.get_all_owners()
        assert owners["iface:ipvlan-l2"].requires == ["iface:enp0s31f6"]
        assert owners["iface:ipvlan-l2.100"].requires == ["iface:enp0s31f6.100"]


class TestRenderNetworkdDropins:
    """Tests for render_networkd_dropins()."""

    def test_render_service_32_dropin(self, tmp_path: Path, write_file: Any) -> None:
        """service-32 services get address drop-ins."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        # Create base .network file
        write_file(output_dir / "21-vlan.network", "[Match]\nName=vlan0\n")

        # Create drop-in directory
        dropin_dir = output_dir / "21-vlan.network.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)

        # Create template
        write_file(
            config_root / "_templates" / "hosts" / "service-addr.conf.j2",
            "[Network]\nAddress={{ service_address }}\n",
        )

        # Create service config
        write_file(
            config_root / "services" / "caddy" / "service.yaml",
            "name: caddy\npodman:\n  user: root\n  network: service-32\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"vlan0": {"vlan": "services"}}}},
            "services": {"caddy": {"vlan": "services", "address": "172.20.20.200/32"}},
        }

        render_networkd_dropins(
            "phobos",
            ["caddy"],
            network,
            config_root,
            output_dir,
        )

        dropin_file = dropin_dir / "200-caddy.conf"
        assert dropin_file.exists()
        assert "[Network]" in dropin_file.read_text()
        assert "172.20.20.200" in dropin_file.read_text()

    def test_render_ipvlan_l2_dropin(self, tmp_path: Path, write_file: Any) -> None:
        """ipvlan-l2 services get route drop-ins."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        # Create base .network file
        write_file(output_dir / "21-ipvlan.network", "[Match]\nName=ipvlan-l2\n")

        # Create drop-in directory
        dropin_dir = output_dir / "21-ipvlan.network.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)

        # Create route template
        write_file(
            config_root / "_templates" / "hosts" / "service-route.conf.j2",
            "[Route]\nDestination={{ service_address }}\n",
        )

        # Create service config
        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            "name: blocky\npodman:\n  user: root\n  network: ipvlan-l2\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"ipvlan-l2": {"vlan": "dmz"}}}},
            "services": {"blocky": {"vlan": "dmz", "address": "172.20.30.234/32"}},
        }

        render_networkd_dropins(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
        )

        dropin_file = dropin_dir / "234-blocky.conf"
        assert dropin_file.exists()
        assert "[Route]" in dropin_file.read_text()
        assert "172.20.30.234" in dropin_file.read_text()

    def test_skips_non_networkd_services(self, tmp_path: Path, write_file: Any) -> None:
        """Services without networkd mode are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        dropin_dir = output_dir / "21-vlan.network.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)

        write_file(output_dir / "21-vlan.network", "[Match]\nName=vlan0\n")

        # Service with no network metadata
        write_file(
            config_root / "services" / "coredns-common" / "service.yaml",
            "name: coredns-common\ncomposition: {}\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"vlan0": {"vlan": "services"}}}},
            "services": {},
        }

        # Should not raise; just skip the service
        render_networkd_dropins(
            "phobos",
            ["coredns-common"],
            network,
            config_root,
            output_dir,
        )

        # No drop-in should be created
        assert not list(dropin_dir.glob("*.conf"))

    def test_missing_service_in_network_raises(self, tmp_path: Path, write_file: Any) -> None:
        """RenderError raised if service not in network.yaml."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        write_file(output_dir / "21-vlan.network", "[Match]\nName=vlan0\n")
        (output_dir / "21-vlan.network.d").mkdir(parents=True, exist_ok=True)

        write_file(
            config_root / "services" / "caddy" / "service.yaml",
            "name: caddy\npodman:\n  user: root\n  network: service-32\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"vlan0": {"vlan": "services"}}}},
            "services": {},
        }

        with pytest.raises(RenderError, match="missing from network.yaml"):
            render_networkd_dropins(
                "phobos",
                ["caddy"],
                network,
                config_root,
                output_dir,
            )

    def test_missing_dropin_dir_for_vlan_raises(self, tmp_path: Path, write_file: Any) -> None:
        """RenderError raised if VLAN has no drop-in directory."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        write_file(
            config_root / "services" / "caddy" / "service.yaml",
            "name: caddy\npodman:\n  user: root\n  network: service-32\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"vlan0": {"vlan": "services"}}}},
            "services": {
                "caddy": {
                    "vlan": "services",
                    "address": "172.20.20.200/32",
                }
            },
        }

        with pytest.raises(RenderError, match="No drop-in directory found"):
            render_networkd_dropins(
                "phobos",
                ["caddy"],
                network,
                config_root,
                output_dir,
            )

    def test_empty_service_list_is_noop(self, tmp_path: Path) -> None:
        """Empty service list doesn't crash."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "etc/systemd/network"

        # Should not raise
        render_networkd_dropins(
            "phobos",
            [],
            {},
            config_root,
            output_dir,
        )

    def test_dropin_owner_ref_uses_match_interface(self, tmp_path: Path, write_file: Any) -> None:
        """Drop-in metadata uses iface owner from [Match] Name rather than filename stem."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "output"
        output_dir = rendered_root / "etc/systemd/network"
        collector = ArtifactCollector()

        write_file(output_dir / "21-vlan.network", "[Match]\nName=vlan0\n")

        dropin_dir = output_dir / "21-vlan.network.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)

        write_file(
            config_root / "_templates" / "hosts" / "service-addr.conf.j2",
            "[Network]\nAddress={{ service_address }}\n",
        )

        write_file(
            config_root / "services" / "caddy" / "service.yaml",
            "name: caddy\npodman:\n  user: root\n  network: service-32\n",
        )

        network = {
            "hosts": {"phobos": {"interfaces": {"vlan0": {"vlan": "services"}}}},
            "services": {"caddy": {"vlan": "services", "address": "172.20.20.200/32"}},
        }

        render_networkd_dropins(
            "phobos",
            ["caddy"],
            network,
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = collector.get_artifacts_by_owner("iface:vlan0")
        assert len(artifacts) == 1
        assert artifacts[0].kind == "networkd.dropin"
        assert artifacts[0].target_path == "/etc/systemd/network/21-vlan.network.d/200-caddy.conf"
