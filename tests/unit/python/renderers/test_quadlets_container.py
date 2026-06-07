"""Unit tests for quadlets renderer (container focus)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.errors import RenderError
from abhaile.renderers.collector import ArtifactCollector


class TestRenderServiceQuadlets:
    """Tests for render_service_quadlets()."""

    def test_skip_services_without_podman(self, tmp_path: Path, write_file: Any) -> None:
        """Services without podman config are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "systemd-service" / "service.yaml",
            "name: systemd-service\ncomposition: {}\n",
        )

        network: dict[str, Any] = {"services": {}}

        render_service_quadlets(
            "phobos",
            ["systemd-service"],
            network,
            config_root,
            output_dir,
        )

        # No quadlet files should be generated
        assert not (output_dir / "systemd-service").exists()

    def test_render_simple_container_with_image(self, tmp_path: Path, write_file: Any) -> None:
        """Simple container with image is rendered correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "blocky" / "quadlets" / "image.image",
            "[Image]\nImage=ghcr.io/0xerr0r/blocky:v0.27.0\n",
        )

        write_file(
            config_root / "services" / "blocky" / "quadlets" / "container.container.j2",
            """[Unit]
Description=Blocky
After=network-online.target

[Container]
Image={{ image }}
Network={{ network.services[service_name].vlan }}.network

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
""",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            """[Unit]
Description={{ vlan_name }} network

[Network]
Driver=ipvlan
Subnet={{ network.vlans[vlan_name].cidr }}
""",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"blocky": {"vlan": "services", "address": "172.20.20.234/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
        )

        container_file = output_dir / "blocky" / "etc/containers/systemd/blocky.container"
        image_file = output_dir / "blocky" / "etc/containers/systemd/blocky.image"

        assert container_file.exists()
        assert image_file.exists()

        container_content = container_file.read_text()
        assert "Image=blocky.image" in container_content
        assert "Network=services.network" in container_content

        image_content = image_file.read_text()
        assert "ghcr.io/0xerr0r/blocky:v0.27.0" in image_content

    def test_render_named_volumes(self, tmp_path: Path, write_file: Any) -> None:
        """Named volumes generate .volume files and volume lines."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "vault" / "service.yaml",
            """name: vault
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /srv/vault/config
        mount_path: /vault/config
      - name: data
        host_path: /srv/vault/data
        mount_path: /vault/data
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "vault" / "quadlets" / "image.image",
            "[Image]\nImage=vault:latest\n",
        )

        write_file(
            config_root / "services" / "vault" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"vault": {"vlan": "services", "address": "172.20.20.100/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["vault"],
            network,
            config_root,
            output_dir,
        )

        # Check volume files exist
        config_vol = output_dir / "vault" / "etc/containers/systemd/vault-config.volume"
        data_vol = output_dir / "vault" / "etc/containers/systemd/vault-data.volume"

        assert config_vol.exists()
        assert data_vol.exists()

        # Check container references volumes
        container_file = output_dir / "vault" / "etc/containers/systemd/vault.container"
        container_content = container_file.read_text()

        assert "Volume=vault-config.volume:/vault/config" in container_content
        assert "Volume=vault-data.volume:/vault/data" in container_content

    def test_shared_volumes_no_service_prefix(self, tmp_path: Path, write_file: Any) -> None:
        """Shared volumes are named without service prefix."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: host-certs
        host_path: /etc/ssl/certs
        mount_path: /etc/ssl/certs
        mode: ro
        shared: true
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "blocky" / "quadlets" / "image.image",
            "[Image]\nImage=blocky:latest\n",
        )

        write_file(
            config_root / "services" / "blocky" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"blocky": {"vlan": "services", "address": "172.20.20.234/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
        )

        # Shared volume should be in _shared directory with non-prefixed name
        shared_vol = output_dir / "_shared" / "etc/containers/systemd/host-certs.volume"
        assert shared_vol.exists()

        # Non-shared volume directory should not have this file
        non_shared_vol = output_dir / "blocky" / "etc/containers/systemd/host-certs.volume"
        assert not non_shared_vol.exists()

        # Container should reference the shared volume
        container_file = output_dir / "blocky" / "etc/containers/systemd/blocky.container"
        container_content = container_file.read_text()
        assert "Volume=host-certs.volume:/etc/ssl/certs:ro" in container_content

    def test_mounted_files_in_volume_lines(self, tmp_path: Path, write_file: Any) -> None:
        """Mounted files appear in volume_lines alongside named volumes."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy" / "service.yaml",
            """name: caddy
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /srv/caddy/config
        mount_path: /config
    mounted_files:
      - host_path: /srv/caddy/Caddyfile
        mount_path: /etc/caddy/Caddyfile
        mode: ro
""",
        )

        write_file(
            config_root / "services" / "caddy" / "quadlets" / "image.image",
            "[Image]\nImage=caddy:latest\n",
        )

        write_file(
            config_root / "services" / "caddy" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"caddy": {"vlan": "services", "address": "172.20.20.100/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["caddy"],
            network,
            config_root,
            output_dir,
        )

        container_file = output_dir / "caddy" / "etc/containers/systemd/caddy.container"
        container_content = container_file.read_text()

        # Named volume reference
        assert "Volume=caddy-config.volume:/config" in container_content
        # Mounted file (raw path)
        assert "Volume=/srv/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" in container_content

    def test_rootless_container_path(self, tmp_path: Path, write_file: Any) -> None:
        """Rootless containers are placed in home directory."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "vault-agent" / "service.yaml",
            """name: vault-agent
podman:
  user: abhaile
  network: host
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "vault-agent" / "quadlets" / "image.image",
            "[Image]\nImage=vault:latest\n",
        )

        write_file(
            config_root / "services" / "vault-agent" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        network: dict[str, Any] = {}

        render_service_quadlets(
            "phobos",
            ["vault-agent"],
            network,
            config_root,
            output_dir,
        )

        # Rootless container should be in home directory
        container_file = (
            output_dir
            / "vault-agent"
            / "home/abhaile/.config/containers/systemd/vault-agent.container"
        )
        assert container_file.exists()

    def test_network_quadlets_deduped(self, tmp_path: Path, write_file: Any) -> None:
        """Network quadlets are generated once per VLAN."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Two services using the same VLAN
        for service in ["blocky", "vault"]:
            write_file(
                config_root / "services" / service / "service.yaml",
                f"""name: {service}
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
            )

            write_file(
                config_root / "services" / service / "quadlets" / "image.image",
                "[Image]\nImage=test:latest\n",
            )

            write_file(
                config_root / "services" / service / "quadlets" / "container.container.j2",
                "[Container]\nImage={{ image }}\n",
            )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            """[Unit]
Description={{ vlan_name }} network

[Network]
Driver=ipvlan
Subnet={{ network.vlans[vlan_name].cidr }}
""",
        )

        network: dict[str, Any] = {
            "vlans": {
                "services": {
                    "cidr": "172.20.20.0/24",
                }
            },
            "services": {
                "blocky": {"vlan": "services", "address": "172.20.20.234/32"},
                "vault": {"vlan": "services", "address": "172.20.20.100/32"},
            },
        }

        render_service_quadlets(
            "phobos",
            ["blocky", "vault"],
            network,
            config_root,
            output_dir,
        )

        # Only one network file should be generated for the shared VLAN
        network_file = output_dir / "podman-networks" / "etc/containers/systemd/services.network"
        assert network_file.exists()

    def test_build_file_rendering(self, tmp_path: Path, write_file: Any) -> None:
        """Build files are copied and referenced in container."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "coredns-custom" / "service.yaml",
            """name: coredns-custom
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "coredns-custom" / "quadlets" / "build.build",
            "[Build]\nDockerfile=./Dockerfile\n",
        )

        write_file(
            config_root / "services" / "coredns-custom" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ build }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"coredns-custom": {"vlan": "services", "address": "172.20.20.100/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["coredns-custom"],
            network,
            config_root,
            output_dir,
        )

        build_file = output_dir / "coredns-custom" / "etc/containers/systemd/coredns-custom.build"
        container_file = (
            output_dir / "coredns-custom" / "etc/containers/systemd/coredns-custom.container"
        )

        assert build_file.exists()
        assert "Dockerfile=./Dockerfile" in build_file.read_text()

        container_content = container_file.read_text()
        assert "Image=coredns-custom.build" in container_content

    def test_missing_quadlets_directory_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing quadlets directory raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "broken-service" / "service.yaml",
            """name: broken-service
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        network: dict[str, Any] = {"services": {"broken-service": {"vlan": "services"}}}

        with pytest.raises(RenderError, match="Quadlets directory missing"):
            render_service_quadlets(
                "phobos",
                ["broken-service"],
                network,
                config_root,
                output_dir,
            )

    def test_duplicate_host_path_error(self, tmp_path: Path, write_file: Any) -> None:
        """Duplicate host_path without shared=true raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "service1" / "service.yaml",
            """name: service1
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /shared/path
        mount_path: /config
      - name: data
        host_path: /shared/path
        mount_path: /data
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "service1" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        write_file(
            config_root / "services" / "service1" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"service1": {"vlan": "services"}},
        }

        # Duplicate host_path should raise error unless declared shared=true.
        with pytest.raises(RenderError, match="must be declared with shared=true"):
            render_service_quadlets(
                "phobos",
                ["service1"],
                network,
                config_root,
                output_dir,
            )

    def test_same_host_path_different_services_requires_shared(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Same host_path under same user requires shared=true across services."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "service1" / "service.yaml",
            """name: service1
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /shared/path
        mount_path: /config
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "service1" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        write_file(
            config_root / "services" / "service1" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "services" / "service2" / "service.yaml",
            """name: service2
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /shared/path
        mount_path: /config
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "service2" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        write_file(
            config_root / "services" / "service2" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network_multi: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {
                "service1": {"vlan": "services"},
                "service2": {"vlan": "services"},
            },
        }

        with pytest.raises(RenderError, match="must be declared with shared=true"):
            render_service_quadlets(
                "phobos",
                ["service1", "service2"],
                network_multi,
                config_root,
                output_dir,
            )

    def test_registers_container_metadata(self, tmp_path: Path, write_file: Any) -> None:
        """Container quadlet files are registered with correct kind and owner_ref."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )
        write_file(
            config_root / "services" / "blocky" / "quadlets" / "image.image",
            "[Image]\nImage=blocky:latest\n",
        )
        write_file(
            config_root / "services" / "blocky" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"blocky": {"vlan": "services", "address": "172.20.20.10/32"}},
        }

        collector = ArtifactCollector()
        render_service_quadlets(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = {a.render_path: a for a in collector.get_all_artifacts()}
        owners = collector.get_all_owners()

        container_key = next(k for k in artifacts if k.endswith("blocky.container"))
        container_art = artifacts[container_key]
        assert container_art.kind == "quadlet.container"
        assert container_art.owner_ref == "unit:blocky.service"
        assert container_art.target_path == "/etc/containers/systemd/blocky.container"

        image_key = next(k for k in artifacts if k.endswith("blocky.image"))
        image_art = artifacts[image_key]
        assert image_art.kind == "quadlet.image"
        assert image_art.owner_ref == "unit:blocky-image.service"

        network_key = next(k for k in artifacts if k.endswith("services.network"))
        network_art = artifacts[network_key]
        assert network_art.kind == "quadlet.network"
        assert network_art.owner_ref == "unit:services-network.service"
        assert network_art.apply_hints == {"rootless": False, "shared": True}
        assert owners["unit:services-network.service"].apply_hints == {
            "rootless": False,
            "shared": True,
        }
        assert owners["unit:blocky.service"].requires == [
            "unit:blocky-image.service",
            "unit:services-network.service",
        ]

        assert "unit:blocky.service" in owners
        assert "unit:blocky-image.service" in owners
        assert "unit:services-network.service" in owners
