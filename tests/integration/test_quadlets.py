"""Integration tests for quadlets rendering with actual config."""

from pathlib import Path

import pytest

from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.config import read_yaml

pytestmark = pytest.mark.integration


class TestQuadretsIntegration:
    """Integration tests using actual repository configuration."""

    def test_render_actual_blocky_service(self, tmp_path: Path) -> None:
        """Test rendering blocky-a service with actual config structure."""
        # Use __file__ to navigate from tests/ dir to repo root
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky-a" / "service.yaml"
        assert blocky_yaml.exists(), f"Test requires blocky-a service config at {blocky_yaml}"

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["blocky-a"],
            network,
            config_root,
            output_dir,
        )

        # Verify quadlet files exist
        service_dir = output_dir / "blocky-a" / "etc/containers/systemd"
        container = service_dir / "blocky-a.container"
        assert container.exists()
        assert not (service_dir / "blocky-a.image").exists()
        container_content = container.read_text(encoding="utf-8")
        assert "Image=ghcr.io/0xerr0r/blocky:v0.27.0" in container_content
        assert "Pull=missing" in container_content

        # Verify volume files for shared volumes
        shared_dir = output_dir / "_shared" / "etc/containers/systemd"
        assert (shared_dir / "host-certs.volume").exists()

    def test_render_actual_vault_service(self, tmp_path: Path) -> None:
        """Test rendering vault service with volumes."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        vault_yaml = config_root / "services" / "vault" / "service.yaml"
        if not vault_yaml.exists():
            pytest.skip(f"Test requires vault service config at {vault_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["vault"],
            network,
            config_root,
            output_dir,
        )

        service_dir = output_dir / "vault" / "etc/containers/systemd"
        container = service_dir / "vault.container"
        assert container.exists()
        assert not (service_dir / "vault.image").exists()
        container_content = container.read_text(encoding="utf-8")
        assert "Image=docker.io/hashicorp/vault:1.21.4" in container_content
        assert "Pull=missing" in container_content
        assert (service_dir / "vault-config.volume").exists()
        assert (service_dir / "vault-data.volume").exists()

    def test_render_network_quadlets_for_vlans(self, tmp_path: Path) -> None:
        """Test that network quadlets are generated for used VLANs."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky-a" / "service.yaml"
        assert blocky_yaml.exists(), f"Test requires blocky-a service config at {blocky_yaml}"

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["blocky-a", "vault"],
            network,
            config_root,
            output_dir,
        )

        networks_dir = output_dir / "podman-networks" / "etc/containers/systemd"
        assert (networks_dir / "services.network").exists()

        # Verify network file is properly formatted
        network_content = (networks_dir / "services.network").read_text()
        assert "[Network]" in network_content
        assert "Driver=ipvlan" in network_content

    def test_deterministic_output(self, tmp_path: Path) -> None:
        """Test that rendering is deterministic (same input = same output)."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky-a" / "service.yaml"
        assert blocky_yaml.exists(), f"Test requires blocky-a service config at {blocky_yaml}"

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        network = read_yaml(network_yaml)

        # Render twice
        output_dir1 = tmp_path / "output1"
        output_dir2 = tmp_path / "output2"

        render_service_quadlets(
            "phobos", ["blocky-a"], network, config_root, output_dir1 / "services"
        )
        render_service_quadlets(
            "phobos", ["blocky-a"], network, config_root, output_dir2 / "services"
        )

        # Compare all rendered files
        container_file1 = (
            output_dir1 / "services" / "blocky-a" / "etc/containers/systemd/blocky-a.container"
        )
        container_file2 = (
            output_dir2 / "services" / "blocky-a" / "etc/containers/systemd/blocky-a.container"
        )

        assert container_file1.exists() and container_file2.exists()
        assert container_file1.read_text() == container_file2.read_text()

        assert not (
            output_dir1 / "services" / "blocky-a" / "etc/containers/systemd/blocky-a.image"
        ).exists()
        assert not (
            output_dir2 / "services" / "blocky-a" / "etc/containers/systemd/blocky-a.image"
        ).exists()

    @pytest.mark.slow
    def test_render_all_podman_services(self, tmp_path: Path) -> None:
        """Test rendering all podman services in mapping."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        mapping = read_yaml(mapping_yaml)
        network = read_yaml(network_yaml)

        # Extract services for phobos
        phobos_services = []
        for entry in mapping.get("abhaile", []):
            if isinstance(entry, dict) and "phobos" in entry:
                phobos_services = entry["phobos"]
                break

        if not phobos_services:
            pytest.skip("No services mapped to phobos")

        output_dir = tmp_path / "services"

        render_service_quadlets(
            "phobos",
            phobos_services,
            network,
            config_root,
            output_dir,
        )

        # Verify at least one quadlet was generated
        container_files = list(output_dir.glob("*/etc/containers/systemd/*.container"))
        assert len(container_files) > 0

    def test_render_actual_authelia_pod(self, tmp_path: Path) -> None:
        """Test rendering authelia pod service with actual config."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        authelia_yaml = config_root / "services" / "authelia" / "service.yaml"
        if not authelia_yaml.exists():
            pytest.skip(f"Test requires authelia service config at {authelia_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["authelia"],
            network,
            config_root,
            output_dir,
        )

        # Verify pod quadlet exists with correct naming
        pod_file = output_dir / "authelia" / "etc/containers/systemd" / "authelia-app.pod"
        assert pod_file.exists(), "Pod quadlet should be named authelia-app.pod"

        pod_content = pod_file.read_text()
        assert "[Pod]" in pod_content
        assert "Network=" in pod_content

        # Verify authelia container exists with correct naming
        authelia_container = (
            output_dir / "authelia" / "etc/containers/systemd" / "authelia-app-authelia.container"
        )
        assert (
            authelia_container.exists()
        ), "Container should be named authelia-app-authelia.container"

        authelia_content = authelia_container.read_text()
        assert "Pod=authelia-app.pod" in authelia_content
        assert "[Container]" in authelia_content
        assert (
            "After=abhaile-secrets-ready.service authelia-config.service "
            "authelia-app-redis.service"
        ) in authelia_content
        assert (
            "Requires=abhaile-secrets-ready.service authelia-config.service "
            "authelia-app-redis.service"
        ) in authelia_content

        assert "Image=docker.io/authelia/authelia:4.39.13" in authelia_content
        assert "Pull=missing" in authelia_content

        # Verify authelia image quadlet is not rendered
        authelia_image = (
            output_dir / "authelia" / "etc/containers/systemd" / "authelia-app-authelia.image"
        )
        assert not authelia_image.exists()

        # Verify redis container exists with correct naming
        redis_container = (
            output_dir / "authelia" / "etc/containers/systemd" / "authelia-app-redis.container"
        )
        assert (
            redis_container.exists()
        ), "Redis container should be named authelia-app-redis.container"

        redis_content = redis_container.read_text()
        assert "Pod=authelia-app.pod" in redis_content
        assert "[Container]" in redis_content
        assert (
            "Requires=abhaile-secrets-ready.service authelia-redis-conf.service"
        ) in redis_content
        assert "After=abhaile-secrets-ready.service authelia-redis-conf.service" in redis_content
        assert "HealthStartPeriod=10s" in redis_content
        assert "Notify=healthy" in redis_content
        assert "StopSignal=SIGTERM" in redis_content
        assert "StopTimeout=60" in redis_content
        assert "Image=docker.io/library/redis:8.2.2-alpine" in redis_content
        assert "Pull=missing" in redis_content

        # Verify redis image quadlet is not rendered
        redis_image = (
            output_dir / "authelia" / "etc/containers/systemd" / "authelia-app-redis.image"
        )
        assert not redis_image.exists()

        # Verify volume files with correct naming pattern (service-app-container-volume)
        volume_files = list((output_dir / "authelia" / "etc/containers/systemd").glob("*.volume"))
        assert len(volume_files) > 0, "Should have volume files for containers"

        # Check that volume names follow the pattern: authelia-app-{container}-{volume}.volume
        volume_names = [v.name for v in volume_files]
        assert any(
            "authelia-app-authelia-" in name for name in volume_names
        ), "Should have volume(s) for authelia container with authelia-app-authelia- prefix"
        assert any(
            "authelia-app-redis-" in name for name in volume_names
        ), "Should have volume(s) for redis container with authelia-app-redis- prefix"

    def test_render_actual_omada_controller_pod(self, tmp_path: Path) -> None:
        """Test rendering omada-controller pod service with MongoDB."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        omada_yaml = config_root / "services" / "omada-controller" / "service.yaml"
        if not omada_yaml.exists():
            pytest.skip(f"Test requires omada-controller service at {omada_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["omada-controller"],
            network,
            config_root,
            output_dir,
        )

        service_dir = output_dir / "omada-controller" / "etc/containers/systemd"
        pod = service_dir / "omada-controller-app.pod"
        controller = service_dir / "omada-controller-app-omada-controller.container"
        mongodb = service_dir / "omada-controller-app-mongodb.container"

        assert pod.exists()
        assert controller.exists()
        assert mongodb.exists()
        assert not (service_dir / "omada-controller-app-omada-controller.image").exists()
        assert not (service_dir / "omada-controller-app-mongodb.image").exists()

        pod_content = pod.read_text()
        assert "Network=services.network" in pod_content
        assert "IP=172.20.20.220" in pod_content

        controller_content = controller.read_text()
        assert "Pod=omada-controller-app.pod" in controller_content
        assert "Image=docker.io/mbentley/omada-controller:6.2.10.17" in controller_content
        assert "Pull=missing" in controller_content
        assert (
            "After=abhaile-secrets-ready.service omada-controller-env.service "
            "omada-controller-app-mongodb.service" in controller_content
        )
        assert (
            "Requires=abhaile-secrets-ready.service omada-controller-env.service "
            "omada-controller-app-mongodb.service" in controller_content
        )
        assert "EnvironmentFile=/etc/omada-controller/omada-controller.env" in controller_content
        assert "SuccessExitStatus=143" in controller_content

        mongodb_content = mongodb.read_text()
        assert "Pod=omada-controller-app.pod" in mongodb_content
        assert "Image=docker.io/library/mongo:8.0.26" in mongodb_content
        assert "Pull=missing" in mongodb_content
        assert "After=abhaile-secrets-ready.service omada-mongodb-env.service" in mongodb_content
        assert "Requires=abhaile-secrets-ready.service omada-mongodb-env.service" in (
            mongodb_content
        )
        assert "EnvironmentFile=/etc/omada-controller/omada-mongodb.env" in mongodb_content
        assert "Exec=mongod --dbpath /data/db --bind_ip 127.0.0.1" in mongodb_content
        assert "HealthCmd=" in mongodb_content
        assert "Notify=healthy" in mongodb_content
        assert "StopSignal=SIGTERM" in mongodb_content
        assert "StopTimeout=60" in mongodb_content
        assert "SuccessExitStatus=143" in mongodb_content
        assert (
            "Volume=/srv/omada-controller/mongodb/initdb/omada.js:/docker-entrypoint-initdb.d/omada.js:ro"
            in mongodb_content
        )
        for unmanaged_bind_dir in (
            "srv/omada-controller/omada-controller/cert",
            "srv/omada-controller/omada-controller/data",
            "srv/omada-controller/omada-controller/logs",
        ):
            assert not (output_dir / f"omada-controller/{unmanaged_bind_dir}").exists()
        for managed_bind_dir in (
            "srv/omada-controller/mongodb/config",
            "srv/omada-controller/mongodb/data",
        ):
            assert (output_dir / f"omada-controller/{managed_bind_dir}").is_dir()

        # Verify network quadlet
        network_file = (
            output_dir / "podman-networks" / "etc/containers/systemd" / "services.network"
        )
        assert network_file.exists(), "Network quadlet should be generated for pod's VLAN"
