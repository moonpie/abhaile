"""Unit tests for quadlets renderer (pod focus)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.errors import RenderError
from abhaile.utils.artifact_collector import ArtifactCollector


class TestRenderServiceQuadlets:
    """Tests for render_service_quadlets()."""

    def test_skip_services_with_pods(self, tmp_path: Path, write_file: Any) -> None:
        """Services with pod composition render pod quadlets."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "multi-container" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        write_file(
            config_root / "services" / "multi-container" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root
            / "services"
            / "multi-container"
            / "quadlets"
            / "app"
            / "container.container.j2",
            "[Container]\nPod={{ pod }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
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

    def test_render_pod_with_containers(self, tmp_path: Path, write_file: Any) -> None:
        """Pod with multiple containers renders correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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
        write_file(
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
        write_file(
            config_root / "services" / "authelia" / "quadlets" / "authelia" / "image.image",
            "[Image]\nImage=authelia:latest\n",
        )

        write_file(
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
        write_file(
            config_root / "services" / "authelia" / "quadlets" / "redis" / "image.image",
            "[Image]\nImage=redis:latest\n",
        )

        write_file(
            config_root / "services" / "authelia" / "quadlets" / "redis" / "container.container.j2",
            """[Container]
Pod={{ pod }}
Image={{ image }}
{% for line in volume_lines %}
{{ line }}
{% endfor %}
""",
        )

        # Volume template
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\n",
        )

        # Network template
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"authelia": {"vlan": "services", "address": "172.20.20.10/32"}},
        }

        render_service_quadlets(
            "phobos",
            ["authelia"],
            network,
            config_root,
            output_dir,
        )

        # Check pod file
        pod_file = output_dir / "authelia" / "etc" / "containers" / "systemd" / "authelia-app.pod"
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
            output_dir / "authelia" / "etc" / "containers" / "systemd" / "authelia-app-redis.image"
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
            output_dir / "podman-networks" / "etc" / "containers" / "systemd" / "services.network"
        )
        assert network_file.exists()

    def test_pod_with_shared_volume(self, tmp_path: Path, write_file: Any) -> None:
        """Pod container with shared volume uses unprefixed name."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "mypod" / "quadlets" / "pod.pod.j2",
            "[Unit]\nDescription=mypod\n[Pod]\nNetwork=services.network\n",
        )

        write_file(
            config_root / "services" / "mypod" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root / "services" / "mypod" / "quadlets" / "app" / "container.container.j2",
            """[Container]
Pod={{ pod }}
{% for line in volume_lines %}
{{ line }}
{% endfor %}
""",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
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
            output_dir / "mypod" / "etc" / "containers" / "systemd" / "mypod-app-app.container"
        )
        assert container.exists()
        assert "Volume=shared-data.volume:/data" in container.read_text()

        # Check shared volume in _shared/
        shared_vol = (
            output_dir / "_shared" / "etc" / "containers" / "systemd" / "shared-data.volume"
        )
        assert shared_vol.exists()
        assert "Device=/shared/data" in shared_vol.read_text()

    def test_pod_container_with_build_file(self, tmp_path: Path, write_file: Any) -> None:
        """Pod container with build file is rendered correctly."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "custompod" / "quadlets" / "pod.pod.j2",
            "[Pod]\nNetwork=services.network\n",
        )

        write_file(
            config_root / "services" / "custompod" / "quadlets" / "custom" / "build.build",
            "[Build]\nImageTag=custom:latest\n",
        )

        write_file(
            config_root
            / "services"
            / "custompod"
            / "quadlets"
            / "custom"
            / "container.container.j2",
            "[Container]\nPod={{ pod }}\nImage={{ build }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
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

    def test_pod_missing_container_name(self, tmp_path: Path, write_file: Any) -> None:
        """Pod container without name raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "badpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        network: dict[str, Any] = {"services": {}}

        with pytest.raises(RenderError, match="Container missing 'name'"):
            render_service_quadlets(
                "phobos",
                ["badpod"],
                network,
                config_root,
                output_dir,
            )

    def test_pod_missing_container_directory(self, tmp_path: Path, write_file: Any) -> None:
        """Pod with missing container directory raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "badpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        network: dict[str, Any] = {"services": {}}

        with pytest.raises(RenderError, match="Container directory missing"):
            render_service_quadlets(
                "phobos",
                ["badpod"],
                network,
                config_root,
                output_dir,
            )

    def test_pod_rootless_user(self, tmp_path: Path, write_file: Any) -> None:
        """Pod with rootless user renders to correct path."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
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

        write_file(
            config_root / "services" / "userpod" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        write_file(
            config_root / "services" / "userpod" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root / "services" / "userpod" / "quadlets" / "app" / "container.container.j2",
            "[Container]\nPod={{ pod }}\n",
        )

        network: dict[str, Any] = {"services": {}}

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

    def test_registers_pod_metadata(self, tmp_path: Path, write_file: Any) -> None:
        """Pod and container quadlet files are registered with correct kind and owner_ref."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
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
        write_file(
            config_root / "services" / "authelia" / "quadlets" / "pod.pod.j2",
            "[Pod]\nNetwork={{ network.services[service_name].vlan }}.network\n",
        )
        write_file(
            config_root / "services" / "authelia" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=authelia:latest\n",
        )
        write_file(
            config_root / "services" / "authelia" / "quadlets" / "app" / "container.container.j2",
            "[Container]\nPod={{ pod }}\nImage={{ image }}\n",
        )
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\nDriver=ipvlan\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"authelia": {"vlan": "services", "address": "172.20.20.20/32"}},
        }

        collector = ArtifactCollector()
        render_service_quadlets(
            "phobos",
            ["authelia"],
            network,
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = {a.render_path: a for a in collector.get_all_artifacts()}
        owners = collector.get_all_owners()

        pod_key = next(k for k in artifacts if k.endswith("authelia-app.pod"))
        pod_art = artifacts[pod_key]
        assert pod_art.kind == "quadlet.pod"
        assert pod_art.owner_ref == "unit:authelia-app.service"
        assert pod_art.target_path == "/etc/containers/systemd/authelia-app.pod"
        assert pod_art.apply_hints == {"rootless": False}

        container_key = next(k for k in artifacts if k.endswith("authelia-app-app.container"))
        container_art = artifacts[container_key]
        assert container_art.kind == "quadlet.container"
        assert container_art.owner_ref == "unit:authelia-app-app.service"

        image_key = next(k for k in artifacts if k.endswith("authelia-app-app.image"))
        image_art = artifacts[image_key]
        assert image_art.kind == "quadlet.image"
        assert image_art.owner_ref == "unit:authelia-app-app-image.service"

        assert "unit:authelia-app.service" in owners
        assert "unit:authelia-app-app.service" in owners
        assert "unit:authelia-app-app-image.service" in owners
        assert owners["unit:authelia-app.service"].apply_hints == {"rootless": False}
        assert owners["unit:authelia-app.service"].requires == [
            "unit:services-network.service",
        ]
        assert owners["unit:authelia-app-app.service"].requires == [
            "unit:authelia-app-app-image.service",
            "unit:authelia-app.service",
        ]
