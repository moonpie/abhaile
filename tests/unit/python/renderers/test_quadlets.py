"""Unit tests for quadlets renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from renderers.quadlets import render_service_quadlets
from utils.errors import RenderError


def _write(path: Path, content: str) -> None:
    """Helper to write file with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestRenderServiceQuadlets:
    """Tests for render_service_quadlets()."""

    def test_skip_services_without_podman(self, tmp_path: Path) -> None:
        """Services without podman config are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "systemd-service" / "service.yaml",
            "name: systemd-service\ncomposition: {}\n",
        )

        network = {"services": {}}

        render_service_quadlets(
            "phobos",
            ["systemd-service"],
            network,
            config_root,
            output_dir,
        )

        # No quadlet files should be generated
        assert not (output_dir / "systemd-service").exists()

    def test_skip_services_with_pods(self, tmp_path: Path) -> None:
        """Services with pod composition render pod quadlets."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "multi-container" / "service.yaml",
            """name: multi-container
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: app
        named_volumes: []
        mounted_files: []
""",
        )

        _write(
            config_root / "services" / "multi-container" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        _write(
            config_root
            / "services"
            / "multi-container"
            / "quadlets"
            / "app"
            / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        _write(
            config_root
            / "services"
            / "multi-container"
            / "quadlets"
            / "app"
            / "container.container.j2",
            "[Container]\nPod={{ pod }}\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"multi-container": {"vlan": "services"}},
        }

        render_service_quadlets(
            "phobos",
            ["multi-container"],
            network,
            config_root,
            output_dir,
        )

        # Pod quadlet files should be generated
        pod_file = (
            output_dir
            / "multi-container"
            / "etc"
            / "containers"
            / "systemd"
            / "multi-container-app.pod"
        )
        assert pod_file.exists()

        container_file = (
            output_dir
            / "multi-container"
            / "etc"
            / "containers"
            / "systemd"
            / "multi-container-app-app.container"
        )
        assert container_file.exists()

    def test_render_simple_container_with_image(self, tmp_path: Path) -> None:
        """Simple container with image is rendered correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "blocky" / "quadlets" / "image.image",
            "[Image]\nImage=ghcr.io/0xerr0r/blocky:v0.27.0\n",
        )

        _write(
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

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            """[Unit]
Description={{ vlan_name }} network

[Network]
Driver=ipvlan
Subnet={{ network.vlans[vlan_name].cidr }}
""",
        )

        network = {
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

        container_file = (
            output_dir / "blocky" / "etc/containers/systemd/blocky.container"
        )
        image_file = output_dir / "blocky" / "etc/containers/systemd/blocky.image"

        assert container_file.exists()
        assert image_file.exists()

        container_content = container_file.read_text()
        assert "Image=blocky.image" in container_content
        assert "Network=services.network" in container_content

        image_content = image_file.read_text()
        assert "ghcr.io/0xerr0r/blocky:v0.27.0" in image_content

    def test_render_named_volumes(self, tmp_path: Path) -> None:
        """Named volumes generate .volume files and volume lines."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "vault" / "quadlets" / "image.image",
            "[Image]\nImage=vault:latest\n",
        )

        _write(
            config_root / "services" / "vault" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network = {
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

    def test_shared_volumes_no_service_prefix(self, tmp_path: Path) -> None:
        """Shared volumes are named without service prefix."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "blocky" / "quadlets" / "image.image",
            "[Image]\nImage=blocky:latest\n",
        )

        _write(
            config_root / "services" / "blocky" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network = {
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
        non_shared_vol = (
            output_dir / "blocky" / "etc/containers/systemd/host-certs.volume"
        )
        assert not non_shared_vol.exists()

        # Container should reference the shared volume
        container_file = (
            output_dir / "blocky" / "etc/containers/systemd/blocky.container"
        )
        container_content = container_file.read_text()
        assert "Volume=host-certs.volume:/etc/ssl/certs:ro" in container_content

    def test_mounted_files_in_volume_lines(self, tmp_path: Path) -> None:
        """Mounted files appear in volume_lines alongside named volumes."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "caddy" / "quadlets" / "image.image",
            "[Image]\nImage=caddy:latest\n",
        )

        _write(
            config_root / "services" / "caddy" / "quadlets" / "container.container.j2",
            """[Container]
Image={{ image }}
{% for v in volume_lines %}
{{ v }}
{% endfor %}
""",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network = {
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
        assert (
            "Volume=/srv/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" in container_content
        )

    def test_rootless_container_path(self, tmp_path: Path) -> None:
        """Rootless containers are placed in home directory."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "vault-agent" / "quadlets" / "image.image",
            "[Image]\nImage=vault:latest\n",
        )

        _write(
            config_root
            / "services"
            / "vault-agent"
            / "quadlets"
            / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        network = {}

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

    def test_network_quadlets_deduped(self, tmp_path: Path) -> None:
        """Network quadlets are generated once per VLAN."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Two services using the same VLAN
        for service in ["blocky", "vault"]:
            _write(
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

            _write(
                config_root / "services" / service / "quadlets" / "image.image",
                "[Image]\nImage=test:latest\n",
            )

            _write(
                config_root
                / "services"
                / service
                / "quadlets"
                / "container.container.j2",
                "[Container]\nImage={{ image }}\n",
            )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            """[Unit]
Description={{ vlan_name }} network

[Network]
Driver=ipvlan
Subnet={{ network.vlans[vlan_name].cidr }}
""",
        )

        network = {
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
        network_file = (
            output_dir / "podman-networks" / "etc/containers/systemd/services.network"
        )
        assert network_file.exists()

    def test_build_file_rendering(self, tmp_path: Path) -> None:
        """Build files are copied and referenced in container."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "coredns-custom" / "quadlets" / "build.build",
            "[Build]\nDockerfile=./Dockerfile\n",
        )

        _write(
            config_root
            / "services"
            / "coredns-custom"
            / "quadlets"
            / "container.container.j2",
            "[Container]\nImage={{ build }}\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {
                "coredns-custom": {"vlan": "services", "address": "172.20.20.100/32"}
            },
        }

        render_service_quadlets(
            "phobos",
            ["coredns-custom"],
            network,
            config_root,
            output_dir,
        )

        build_file = (
            output_dir
            / "coredns-custom"
            / "etc/containers/systemd/coredns-custom.build"
        )
        container_file = (
            output_dir
            / "coredns-custom"
            / "etc/containers/systemd/coredns-custom.container"
        )

        assert build_file.exists()
        assert "Dockerfile=./Dockerfile" in build_file.read_text()

        container_content = container_file.read_text()
        assert "Image=coredns-custom.build" in container_content

    def test_missing_quadlets_directory_error(self, tmp_path: Path) -> None:
        """Missing quadlets directory raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        network = {"services": {"broken-service": {"vlan": "services"}}}

        with pytest.raises(RenderError, match="Quadlets directory missing"):
            render_service_quadlets(
                "phobos",
                ["broken-service"],
                network,
                config_root,
                output_dir,
            )

    def test_duplicate_host_path_error(self, tmp_path: Path) -> None:
        """Duplicate host_path without shared=true raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "service1" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        _write(
            config_root
            / "services"
            / "service1"
            / "quadlets"
            / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Unit]\nDescription={{ vlan_name }} network\n[Network]\nDriver=ipvlan\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"service1": {"vlan": "services"}},
        }

        # First call succeeds
        render_service_quadlets(
            "phobos",
            ["service1"],
            network,
            config_root,
            output_dir,
        )

        # Second call with same service and host_path (simulating another service with same path, non-shared)
        # This would be caught by validation if host_paths_by_user is maintained across calls.
        # For now, we test within a single render call with multiple services.

        _write(
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

        _write(
            config_root / "services" / "service2" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        _write(
            config_root
            / "services"
            / "service2"
            / "quadlets"
            / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {
                "service1": {"vlan": "services"},
                "service2": {"vlan": "services"},
            },
        }

        with pytest.raises(RenderError, match="Host path rendered more than once"):
            render_service_quadlets(
                "phobos",
                ["service1", "service2"],
                network,
                config_root,
                output_dir,
            )

    def test_render_pod_with_containers(self, tmp_path: Path) -> None:
        """Pod with multiple containers renders correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: authelia
        named_volumes:
          - name: config
            host_path: /var/lib/authelia/config
            mount_path: /config
        mounted_files: []
      - name: redis
        named_volumes:
          - name: data
            host_path: /var/lib/authelia/redis
            mount_path: /data
        mounted_files: []
""",
        )

        # Pod template
        _write(
            config_root / "services" / "authelia" / "quadlets" / "pod.pod.j2",
            """[Unit]
Description=authelia pod

[Pod]
Network={{ network.services[service_name].vlan }}.network

[Install]
WantedBy=multi-user.target
""",
        )

        # Authelia container
        _write(
            config_root
            / "services"
            / "authelia"
            / "quadlets"
            / "authelia"
            / "image.image",
            "[Image]\nImage=authelia:latest\n",
        )

        _write(
            config_root
            / "services"
            / "authelia"
            / "quadlets"
            / "authelia"
            / "container.container.j2",
            """[Container]
Pod={{ pod }}
Image={{ image }}
{% for line in volume_lines %}
{{ line }}
{% endfor %}
""",
        )

        # Redis container
        _write(
            config_root
            / "services"
            / "authelia"
            / "quadlets"
            / "redis"
            / "image.image",
            "[Image]\nImage=redis:latest\n",
        )

        _write(
            config_root
            / "services"
            / "authelia"
            / "quadlets"
            / "redis"
            / "container.container.j2",
            """[Container]
Pod={{ pod }}
Image={{ image }}
{% for line in volume_lines %}
{{ line }}
{% endfor %}
""",
        )

        # Volume template
        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\n",
        )

        # Network template
        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {
                "authelia": {"vlan": "services", "address": "172.20.20.10/32"}
            },
        }

        render_service_quadlets(
            "phobos",
            ["authelia"],
            network,
            config_root,
            output_dir,
        )

        # Check pod file
        pod_file = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app.pod"
        )
        assert pod_file.exists()
        pod_content = pod_file.read_text()
        assert "Description=authelia pod" in pod_content
        assert "Network=services.network" in pod_content

        # Check authelia container
        authelia_container = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-authelia.container"
        )
        assert authelia_container.exists()
        authelia_content = authelia_container.read_text()
        assert "Pod=authelia-app.pod" in authelia_content
        assert "Image=authelia-app-authelia.image" in authelia_content
        assert "Volume=authelia-app-authelia-config.volume:/config" in authelia_content

        # Check authelia image
        authelia_image = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-authelia.image"
        )
        assert authelia_image.exists()
        assert "Image=authelia:latest" in authelia_image.read_text()

        # Check redis container
        redis_container = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-redis.container"
        )
        assert redis_container.exists()
        redis_content = redis_container.read_text()
        assert "Pod=authelia-app.pod" in redis_content
        assert "Image=authelia-app-redis.image" in redis_content
        assert "Volume=authelia-app-redis-data.volume:/data" in redis_content

        # Check redis image
        redis_image = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-redis.image"
        )
        assert redis_image.exists()
        assert "Image=redis:latest" in redis_image.read_text()

        # Check volume files
        authelia_config_vol = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-authelia-config.volume"
        )
        assert authelia_config_vol.exists()
        assert "Device=/var/lib/authelia/config" in authelia_config_vol.read_text()

        redis_data_vol = (
            output_dir
            / "authelia"
            / "etc"
            / "containers"
            / "systemd"
            / "authelia-app-redis-data.volume"
        )
        assert redis_data_vol.exists()
        assert "Device=/var/lib/authelia/redis" in redis_data_vol.read_text()

        # Check network quadlet
        network_file = (
            output_dir
            / "podman-networks"
            / "etc"
            / "containers"
            / "systemd"
            / "services.network"
        )
        assert network_file.exists()

    def test_pod_with_shared_volume(self, tmp_path: Path) -> None:
        """Pod container with shared volume uses unprefixed name."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "mypod" / "service.yaml",
            """name: mypod
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: app
        named_volumes:
          - name: shared-data
            host_path: /shared/data
            mount_path: /data
            shared: true
        mounted_files: []
""",
        )

        _write(
            config_root / "services" / "mypod" / "quadlets" / "pod.pod.j2",
            "[Unit]\nDescription=mypod\n[Pod]\nNetwork=services.network\n",
        )

        _write(
            config_root / "services" / "mypod" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        _write(
            config_root
            / "services"
            / "mypod"
            / "quadlets"
            / "app"
            / "container.container.j2",
            """[Container]
Pod={{ pod }}
{% for line in volume_lines %}
{{ line }}
{% endfor %}
""",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"mypod": {"vlan": "services"}},
        }

        render_service_quadlets(
            "phobos",
            ["mypod"],
            network,
            config_root,
            output_dir,
        )

        # Check container references unprefixed shared volume
        container = (
            output_dir
            / "mypod"
            / "etc"
            / "containers"
            / "systemd"
            / "mypod-app-app.container"
        )
        assert container.exists()
        assert "Volume=shared-data.volume:/data" in container.read_text()

        # Check shared volume in _shared/
        shared_vol = (
            output_dir
            / "_shared"
            / "etc"
            / "containers"
            / "systemd"
            / "shared-data.volume"
        )
        assert shared_vol.exists()
        assert "Device=/shared/data" in shared_vol.read_text()

    def test_pod_container_with_build_file(self, tmp_path: Path) -> None:
        """Pod container with build file is rendered correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "custompod" / "service.yaml",
            """name: custompod
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: custom
        named_volumes: []
        mounted_files: []
""",
        )

        _write(
            config_root / "services" / "custompod" / "quadlets" / "pod.pod.j2",
            "[Pod]\nNetwork=services.network\n",
        )

        _write(
            config_root
            / "services"
            / "custompod"
            / "quadlets"
            / "custom"
            / "build.build",
            "[Build]\nImageTag=custom:latest\n",
        )

        _write(
            config_root
            / "services"
            / "custompod"
            / "quadlets"
            / "custom"
            / "container.container.j2",
            "[Container]\nPod={{ pod }}\nImage={{ build }}\n",
        )

        _write(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"custompod": {"vlan": "services"}},
        }

        render_service_quadlets(
            "phobos",
            ["custompod"],
            network,
            config_root,
            output_dir,
        )

        # Check container references build file
        container = (
            output_dir
            / "custompod"
            / "etc"
            / "containers"
            / "systemd"
            / "custompod-app-custom.container"
        )
        assert container.exists()
        assert "Image=custompod-app-custom.build" in container.read_text()

        # Check build file is copied
        build_file = (
            output_dir
            / "custompod"
            / "etc"
            / "containers"
            / "systemd"
            / "custompod-app-custom.build"
        )
        assert build_file.exists()
        assert "ImageTag=custom:latest" in build_file.read_text()

    def test_pod_missing_container_name(self, tmp_path: Path) -> None:
        """Pod container without name raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "badpod" / "service.yaml",
            """name: badpod
podman:
  user: root
composition:
  pod:
    containers:
      - named_volumes: []
""",
        )

        _write(
            config_root / "services" / "badpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        network = {"services": {}}

        with pytest.raises(RenderError, match="Container missing 'name'"):
            render_service_quadlets(
                "phobos",
                ["badpod"],
                network,
                config_root,
                output_dir,
            )

    def test_pod_missing_container_directory(self, tmp_path: Path) -> None:
        """Pod with missing container directory raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "badpod" / "service.yaml",
            """name: badpod
podman:
  user: root
composition:
  pod:
    containers:
      - name: missing
        named_volumes: []
""",
        )

        _write(
            config_root / "services" / "badpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        network = {"services": {}}

        with pytest.raises(RenderError, match="Container directory missing"):
            render_service_quadlets(
                "phobos",
                ["badpod"],
                network,
                config_root,
                output_dir,
            )

    def test_pod_rootless_user(self, tmp_path: Path) -> None:
        """Pod with rootless user renders to correct path."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "userpod" / "service.yaml",
            """name: userpod
podman:
  user: myuser
composition:
  pod:
    containers:
      - name: app
        named_volumes: []
        mounted_files: []
""",
        )

        _write(
            config_root / "services" / "userpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        _write(
            config_root / "services" / "userpod" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        _write(
            config_root
            / "services"
            / "userpod"
            / "quadlets"
            / "app"
            / "container.container.j2",
            "[Container]\nPod={{ pod }}\n",
        )

        network = {"services": {}}

        render_service_quadlets(
            "phobos",
            ["userpod"],
            network,
            config_root,
            output_dir,
        )

        # Check pod file is in rootless path
        pod_file = (
            output_dir
            / "userpod"
            / "home"
            / "myuser"
            / ".config"
            / "containers"
            / "systemd"
            / "userpod-app.pod"
        )
        assert pod_file.exists()

        # Check container file is in rootless path
        container = (
            output_dir
            / "userpod"
            / "home"
            / "myuser"
            / ".config"
            / "containers"
            / "systemd"
            / "userpod-app-app.container"
        )
        assert container.exists()
